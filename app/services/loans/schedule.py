"""Tilgungsplan-Berechnung als reine Funktionen (ohne Datenbank).

Konventionen:
- Monatszins = Jahreszins / 12 (30/360), Zinsen je Rate kaufmännisch auf Cent gerundet.
  Gerechnet wird exakt (Produkt erst, dann eine Division), damit ein exakter halber
  Cent wirklich aufgerundet wird.
- Annuitätendarlehen: feste Rate (Zins + Tilgung); die letzte Rate begleicht die exakte Restschuld.
- Tilgungsdarlehen/Ratenkredit: feste Tilgung, Zinsen auf die Restschuld, die Rate sinkt.
- Rate bzw. Tilgung zu einer Laufzeit (`installments_for_term`): exakt berechnet und auf den
  Cent AUFgerundet; würde der Plan dadurch vor dem Laufzeitende enden (kleine Beträge, lange
  Laufzeit), wird centweise gesenkt, bis er genau die Laufzeit hat.
- Laufzeitende (`final_due`): Die Rate an diesem Tag ist die Schlussrate und begleicht die
  gesamte Restschuld – es gibt nie mehr Raten als vereinbart. Ohne `final_due` läuft der
  Plan mit fester Rate, bis die Restschuld getilgt ist.
- `extra` (Gebühren/Versicherung) kommt je Rate zusätzlich dazu und tilgt nicht.
Banken rechnen teils taggenau; deshalb wird der Plan nach jeder Zahlung ab der
tatsächlichen Restschuld neu berechnet, Abweichungen summieren sich nicht.
"""

import calendar
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
MAX_INSTALLMENTS = 600  # 50 Jahre
TERM_TOLERANCE_MIN = Decimal("1.00")


class ScheduleError(ValueError):
    def __init__(self, message: str, code: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class PlannedInstallment:
    seq: int
    due_date: date
    interest: Decimal
    principal: Decimal
    extra: Decimal
    remaining_after: Decimal

    @property
    def total(self) -> Decimal:
        return self.interest + self.principal + self.extra


def to_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _ceil_cents(value: Fraction) -> Decimal:
    """Exakter Bruch → auf ganze Cent aufgerundet (ohne Rundungsrauschen)."""
    cents = -((-value * 100) // 1)
    return (Decimal(cents) / 100).quantize(CENT)


def monthly_interest(remaining: Decimal, annual_percent: Decimal) -> Decimal:
    with localcontext(prec=40):
        return to_cents(remaining * annual_percent / Decimal(1200))


def add_months(start: date, months: int, day: int) -> date:
    """Monat addieren; `day` wird auf das Monatsende begrenzt (z. B. 31. → 28./29.2.)."""
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def due_dates(first_due: date, payment_day: int) -> Iterator[date]:
    months = 0
    while True:
        yield add_months(first_due, months, payment_day) if months else first_due
        months += 1


def _check_term(months: int) -> None:
    if months <= 0:
        raise ScheduleError("Laufzeit muss mindestens eine Rate umfassen", "invalid_term")


def annuity_installment(remaining: Decimal, annual_percent: Decimal, months: int) -> Decimal:
    """Exakte Annuität (Zins + Tilgung), auf den Cent aufgerundet."""
    _check_term(months)
    principal, rate = Fraction(remaining), Fraction(annual_percent) / 1200
    exact = principal / months if rate == 0 else principal * rate / (1 - (1 + rate) ** -months)
    return _ceil_cents(exact)


def fixed_principal_for(remaining: Decimal, months: int) -> Decimal:
    _check_term(months)
    return _ceil_cents(Fraction(remaining) / months)


def build_plan(
    *,
    remaining: Decimal,
    annual_percent: Decimal,
    first_due: date,
    payment_day: int,
    installment: Decimal | None = None,
    fixed_principal: Decimal | None = None,
    extra: Decimal = ZERO,
    start_seq: int = 1,
    final_due: date | None = None,
) -> list[PlannedInstallment]:
    """Plan ab `first_due` für die Restschuld `remaining` (positiv).

    Genau eins von `installment` (Annuität: Zins + Tilgung) oder `fixed_principal`
    (Tilgungsdarlehen) muss gesetzt sein. Mit `final_due` begleicht die Rate am
    Laufzeitende die gesamte Restschuld (Schlussrate).
    """
    if (installment is None) == (fixed_principal is None):
        raise ScheduleError("Entweder Rate oder feste Tilgung angeben", "invalid_plan_basis")
    if remaining <= 0:
        return []
    first_interest = monthly_interest(remaining, annual_percent)
    if installment is not None and installment <= first_interest:
        raise ScheduleError(
            "Die Rate deckt nicht einmal die Zinsen – der Kredit würde nie getilgt",
            "never_amortizes",
            {"installment": installment, "first_interest": first_interest},
        )
    if fixed_principal is not None and fixed_principal <= 0:
        raise ScheduleError("Feste Tilgung muss positiv sein", "invalid_plan_basis")

    plan: list[PlannedInstallment] = []
    for seq, due in enumerate(due_dates(first_due, payment_day), start=start_seq):
        if len(plan) >= MAX_INSTALLMENTS:
            raise ScheduleError(
                f"Mehr als {MAX_INSTALLMENTS} Raten – Konditionen prüfen", "term_too_long"
            )
        interest = monthly_interest(remaining, annual_percent)
        if final_due is not None and due >= final_due:
            principal = remaining  # Schlussrate am Laufzeitende
        else:
            principal = installment - interest if installment is not None else fixed_principal
            principal = min(principal, remaining)  # letzte Rate: exakte Restschuld
        remaining -= principal
        plan.append(PlannedInstallment(seq, due, interest, principal, extra, remaining))
        if remaining == 0:
            return plan
    raise AssertionError("unreachable")


def _installments_needed(
    remaining: Decimal, annual_percent: Decimal, installment: Decimal | None, fixed_principal: Decimal | None,
    limit: int,
) -> int:
    """Anzahl Raten mit fester Rate bzw. Tilgung, ohne Laufzeitende (höchstens limit + 1)."""
    count = 0
    while remaining > 0 and count <= limit:
        interest = monthly_interest(remaining, annual_percent)
        principal = installment - interest if installment is not None else fixed_principal
        if principal <= 0:
            return limit + 1
        remaining -= min(principal, remaining)
        count += 1
    return count


def installments_for_term(
    remaining: Decimal, annual_percent: Decimal, months: int, *, annuity: bool
) -> tuple[Decimal | None, Decimal | None]:
    """(installment, fixed_principal), mit denen der Plan genau `months` Raten hat.

    Mit dem Laufzeitende als `final_due` übernimmt die letzte Rate jeden Rundungsrest.
    """
    if annuity:
        value = annuity_installment(remaining, annual_percent, months)
        floor = monthly_interest(remaining, annual_percent) + CENT  # Rate muss tilgen
    else:
        value = fixed_principal_for(remaining, months)
        floor = CENT
    value = max(value, floor)

    def needed(candidate: Decimal) -> int:
        if annuity:
            return _installments_needed(remaining, annual_percent, candidate, None, months)
        return _installments_needed(remaining, annual_percent, None, candidate, months)

    # Aufgerundet kann der Kredit vor dem Laufzeitende getilgt sein – dann centweise senken
    while needed(value) < months and value - CENT >= floor:
        value -= CENT
    if needed(value) < months:
        raise ScheduleError(
            "Laufzeit ist für diesen Betrag zu lang – kürzere Laufzeit oder feste Rate angeben",
            "term_unreachable",
            {"term_months": months, "installments_needed": needed(value)},
        )
    return (value, None) if annuity else (None, value)


def check_term_matches(
    plan: list[PlannedInstallment], months: int, installment: Decimal | None = None
) -> None:
    """Passen vom Nutzer angegebene Rate und Laufzeit zusammen?

    Der Plan muss genau `months` Raten haben, und die Schlussrate darf die Rate höchstens
    um einen Rundungsrest übersteigen (max. 1,00 € bzw. 1 % der Rate).
    """
    if len(plan) != months:
        raise ScheduleError(
            "Rate und Laufzeit passen nicht zusammen",
            "loan_terms_inconsistent",
            {"term_months": months, "installments_needed": len(plan)},
        )
    if installment is not None and plan:
        last = plan[-1].interest + plan[-1].principal
        tolerance = max(TERM_TOLERANCE_MIN, to_cents(installment * Decimal("0.01")))
        if last > installment + tolerance:
            raise ScheduleError(
                "Rate und Laufzeit passen nicht zusammen – die Schlussrate wäre deutlich höher",
                "loan_terms_inconsistent",
                {"term_months": months, "installment": installment, "final_installment": last},
            )


def split_payment(
    amount: Decimal, *, interest_due: Decimal, extra_due: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """Aufteilung einer tatsächlichen Zahlung: zuerst Gebühren, dann Zinsen, Rest Tilgung."""
    extra = min(extra_due, amount)
    interest = min(interest_due, amount - extra)
    return interest, amount - extra - interest, extra


def accrued_interest(remaining: Decimal, annual_percent: Decimal, days: int) -> Decimal:
    """Aufgelaufene Zinsen für freie Zahlungen (Privatkredit), taggenau act/365."""
    if days <= 0 or annual_percent == 0:
        return ZERO
    with localcontext(prec=40):
        return to_cents(remaining * annual_percent * days / Decimal(36500))
