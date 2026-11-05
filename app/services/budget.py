"""Fixkosten und Monats-Spielraum.

Frei verfügbar = Einnahmen − Fixkosten − variable Ausgaben (je Profil und Kalendermonat).

- Einnahmen: reguläre Zeilen in Einnahmen-Kategorien (Rückzahlungen mindern sie).
  Unkategorisierte Eingänge zählen nicht mit, sie werden als `uncategorized_in` gezeigt.
- Fixkosten: aktive Fixkosten und im Monat fällige Kreditraten. Offene Posten zählen mit
  ihrem Planbetrag (das Geld ist reserviert), bezahlte mit dem TATSÄCHLICH gezahlten Betrag –
  eine Mehrzahlung verschwindet so nicht, eine geringere Zahlung gibt den Rest frei
  (eine erkannte Zahlung erledigt den Posten, auch als Teilzahlung).
- Variable Ausgaben: alle tatsächlichen Abflüsse des Monats (Ausgaben-Kategorien,
  unkategorisierte Abflüsse und Kreditzahlungen samt Tilgung), soweit sie nicht schon als
  bezahlter Posten in den Fixkosten stehen. Eine Kreditrate, die erst im Folgemonat bezahlt
  wird, gilt im Fälligkeitsmonat als bezahlt und belastet den Zahlungsmonat als Abfluss;
  Zahlungen auf Kredite ohne Plan sind immer variable Abflüsse.
- Kreditbuchungen (Rate oder Kreditkonto) werden nie einer gewöhnlichen Fixkost zugeordnet.
"""

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, exists, not_, or_
from sqlmodel import Session, func, select

from app import clock
from app.errors import Conflict, Invalid
from app.models import (
    Account,
    AccountType,
    Category,
    FixedCost,
    FixedCostAmount,
    FixedCostPayment,
    Loan,
    LoanPayment,
    LoanScheduleEntry,
    ScheduleStatus,
    Transaction,
    TransactionSource,
    User,
    transaction_line,
)
from app.schemas.budget import FixedCostAmountCreate, FixedCostCreate, FixedCostPaymentCreate
from app.services.common import apply_changes, flush_or_conflict, get_owned
from app.services.loans.core import open_entries, remaining_debt

ZERO = Decimal("0.00")
L = transaction_line.c
_UNIQUE = {"uq_fixed_cost_user_id_name": "Eine Fixkost mit diesem Namen existiert bereits"}


# --- Fixkosten CRUD -----------------------------------------------------------


def _check_category(session: Session, user: User, category_id: int | None) -> None:
    if category_id is None:
        return
    category = get_owned(session, Category, category_id, user.id, "Kategorie")
    if category.type != "expense":
        raise Invalid("Fixkosten brauchen eine Ausgaben-Kategorie", code="fixed_cost_category_type")


def _check_account(session: Session, user: User, account_id: int | None) -> None:
    if account_id is None:
        return
    account = get_owned(session, Account, account_id, user.id, "Konto")
    if account.type == AccountType.LOAN:
        raise Invalid("Fixkosten werden nicht von einem Kreditkonto bezahlt", code="fixed_cost_account_type")


def list_fixed_costs(session: Session, user: User) -> list[FixedCost]:
    query = select(FixedCost).where(FixedCost.user_id == user.id)
    return list(session.exec(query.order_by(FixedCost.due_day, func.lower(FixedCost.name))))


def get_fixed_cost(session: Session, user: User, fixed_cost_id: int) -> FixedCost:
    return get_owned(session, FixedCost, fixed_cost_id, user.id, "Fixkost")


def create_fixed_cost(session: Session, user: User, data: FixedCostCreate) -> FixedCost:
    _check_category(session, user, data.category_id)
    _check_account(session, user, data.account_id)
    fixed = FixedCost(user_id=user.id, **data.model_dump())
    session.add(fixed)
    flush_or_conflict(session, _UNIQUE)
    return fixed


def update_fixed_cost(session: Session, user: User, fixed: FixedCost, changes: dict) -> FixedCost:
    if changes.get("category_id") is not None:
        _check_category(session, user, changes["category_id"])
    if changes.get("account_id") is not None:
        _check_account(session, user, changes["account_id"])
    interval = changes.get("interval_months", fixed.interval_months)
    if interval != 1 and changes.get("first_due_date", fixed.first_due_date) is None:
        raise Invalid("first_due_date angeben, wenn die Fixkost nicht monatlich ist", code="first_due_date_required")
    start = changes.get("start_date", fixed.start_date)
    end = changes.get("end_date", fixed.end_date)
    if start and end and end < start:
        raise Invalid("end_date liegt vor start_date", code="invalid_period")
    changes = dict(changes)
    amount = changes.pop("amount", None)
    apply_changes(fixed, changes)
    if amount is not None and amount != fixed.amount:
        if list_amounts(session, fixed):
            # mit Betragsgeschichte: neuer Betrag ab dem laufenden Monat, frühere Monate bleiben unverändert
            start = month_start(fixed.start_date) if fixed.start_date else None
            valid_from = max(month_start(clock.today()), start) if start else month_start(clock.today())
            set_amount_from(session, fixed, FixedCostAmountCreate(valid_from=valid_from, amount=amount))
        else:
            fixed.amount = amount
    flush_or_conflict(session, _UNIQUE)
    return fixed


def delete_fixed_cost(session: Session, fixed: FixedCost) -> None:
    session.delete(fixed)
    session.flush()


# --- Beträge mit Gültigkeit ------------------------------------------------------------


def list_amounts(session: Session, fixed: FixedCost) -> list[FixedCostAmount]:
    return list(session.exec(
        select(FixedCostAmount).where(FixedCostAmount.fixed_cost_id == fixed.id).order_by(FixedCostAmount.valid_from)
    ))


def set_amount_from(session: Session, fixed: FixedCost, data: FixedCostAmountCreate) -> FixedCostAmount:
    """Betrag ab dem Monat von `valid_from`; der bisherige Betrag gilt davor weiter."""
    month = month_start(data.valid_from)
    history = list_amounts(session, fixed)
    if not history:
        base = month_start(fixed.start_date) if fixed.start_date else date(2000, 1, 1)
        if base < month:
            session.add(FixedCostAmount(fixed_cost_id=fixed.id, valid_from=base, amount=fixed.amount))
    existing = next((a for a in history if a.valid_from == month), None)
    if existing is None:
        existing = FixedCostAmount(fixed_cost_id=fixed.id, valid_from=month, amount=data.amount)
        session.add(existing)
    else:
        existing.amount = data.amount
    if all(a.valid_from <= month for a in history):
        fixed.amount = data.amount  # aktueller Betrag
    session.flush()
    return existing


def amount_for(fixed: FixedCost, first: date, history: dict[int, list[FixedCostAmount]]) -> Decimal:
    entries = [a for a in history.get(fixed.id, []) if a.valid_from <= first]
    return entries[-1].amount if entries else fixed.amount


def _amount_history(session: Session, fixed_ids: list[int]) -> dict[int, list[FixedCostAmount]]:
    history: dict[int, list[FixedCostAmount]] = {}
    if fixed_ids:
        for a in session.exec(select(FixedCostAmount).where(FixedCostAmount.fixed_cost_id.in_(fixed_ids))
                              .order_by(FixedCostAmount.valid_from)):
            history.setdefault(a.fixed_cost_id, []).append(a)
    return history


# --- Feste Zahlungsverknüpfung ----------------------------------------------------


def _linkable_line(session: Session, user: User, transaction_id: int, split_id: int | None):
    """Die Buchungszeile, falls sie als Fixkostenzahlung in Frage kommt (Abfluss, regulär, kein Kredit)."""
    get_owned(session, Transaction, transaction_id, user.id, "Buchung")
    line = session.execute(
        select(L.amount, L.booking_date, L.kind, L.excluded_at, L.source)
        .where(L.transaction_id == transaction_id, L.split_id.is_not_distinct_from(split_id))
    ).first()
    if line is None:
        raise Invalid("Buchungszeile nicht gefunden – bei aufgeteilten Buchungen split_id angeben",
                      code="payment_line_missing")
    loan_payment = session.exec(
        select(LoanPayment.id).where(LoanPayment.payment_transaction_id == transaction_id)
    ).first()
    if (line.amount >= 0 or line.kind != "regular" or line.excluded_at is not None
            or line.source == TransactionSource.LOAN or loan_payment is not None):
        raise Invalid("Nur reguläre Abbuchungen ohne Kreditbezug lassen sich zuordnen", code="payment_not_linkable")
    return line


def link_payment(
    session: Session, user: User, fixed: FixedCost, data: FixedCostPaymentCreate, source: str = "manual"
) -> FixedCostPayment:
    _linkable_line(session, user, data.transaction_id, data.split_id)
    taken = session.exec(
        select(FixedCostPayment).where(
            FixedCostPayment.transaction_id == data.transaction_id,
            FixedCostPayment.split_id.is_not_distinct_from(data.split_id),
        )
    ).first()
    if taken is not None:
        raise Conflict("Diese Zahlung ist bereits einer Fixkost zugeordnet", code="payment_already_linked",
                       details={"fixed_cost_id": taken.fixed_cost_id})
    month = month_start(data.due_month)
    if session.exec(
        select(FixedCostPayment.id).where(
            FixedCostPayment.fixed_cost_id == fixed.id, FixedCostPayment.due_month == month
        )
    ).first():
        raise Conflict("Für diese Fälligkeit ist bereits eine Zahlung zugeordnet", code="due_month_already_paid")
    link = FixedCostPayment(user_id=user.id, fixed_cost_id=fixed.id, transaction_id=data.transaction_id,
                            split_id=data.split_id, due_month=month, source=source)
    session.add(link)
    session.flush()
    return link


def list_payments(session: Session, fixed: FixedCost) -> list[FixedCostPayment]:
    return list(session.exec(
        select(FixedCostPayment).where(FixedCostPayment.fixed_cost_id == fixed.id).order_by(FixedCostPayment.due_month)
    ))


def unlink_payment(session: Session, fixed: FixedCost, link_id: int) -> None:
    link = session.get(FixedCostPayment, link_id)
    if link is None or link.fixed_cost_id != fixed.id:
        from app.errors import NotFound

        raise NotFound(f"Zuordnung {link_id} nicht gefunden")
    session.delete(link)
    session.flush()


# --- Monatsrechnung -------------------------------------------------------------


def month_start(day: date) -> date:
    return day.replace(day=1)


def month_end(first: date) -> date:
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def due_in_month(first: date, due_day: int) -> date:
    return first.replace(day=min(due_day, calendar.monthrange(first.year, first.month)[1]))


def _status(due: date, paid: bool, today: date) -> str:
    if paid:
        return "paid"
    return "overdue" if due < today else "open"


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def is_due_in_month(fixed: FixedCost, first: date) -> bool:
    if fixed.interval_months == 1 or fixed.first_due_date is None:
        return True
    diff = months_between(fixed.first_due_date, first)
    return diff >= 0 and diff % fixed.interval_months == 0


def next_due_month(fixed: FixedCost, first: date) -> date:
    """Erster Fälligkeitsmonat ab `first` (einschließlich)."""
    diff = months_between(fixed.first_due_date, first)
    step = 0 if diff <= 0 else -(-diff // fixed.interval_months) * fixed.interval_months
    total = fixed.first_due_date.year * 12 + fixed.first_due_date.month - 1 + max(step, 0)
    return date(total // 12, total % 12 + 1, 1)


def _active_fixed_costs(session: Session, user_id: int, first: date, last: date) -> list[FixedCost]:
    return list(
        session.exec(
            select(FixedCost)
            .where(
                FixedCost.user_id == user_id,
                FixedCost.active,
                or_(FixedCost.start_date.is_(None), FixedCost.start_date <= last),
                or_(FixedCost.end_date.is_(None), FixedCost.end_date >= first),
            )
            .order_by(FixedCost.due_day, FixedCost.id)
        )
    )


def _payment_candidates(session: Session, user_id: int, fixed: FixedCost, first: date, last: date):
    """Abflüsse im Monat, die zur Fixkost passen (Kategorie und/oder Suchtext)."""
    if fixed.category_id is None and not fixed.match_text:
        return []
    query = (
        select(L.transaction_id, L.split_id, L.amount, L.booking_date)
        .select_from(transaction_line.join(Transaction, Transaction.id == L.transaction_id))
        .where(
            L.user_id == user_id,
            L.kind == "regular",
            L.excluded_at.is_(None),
            L.amount < 0,
            L.booking_date.between(first, last),
            # Kreditraten und Belastungen des Kreditkontos gehören zum Kredit, nicht zur Fixkost
            Transaction.source != TransactionSource.LOAN,
            not_(exists().where(LoanPayment.payment_transaction_id == L.transaction_id)),
        )
        .order_by(L.booking_date, L.transaction_id, L.split_id)
    )
    if fixed.category_id is not None:
        query = query.where(L.category_id == fixed.category_id)
    if fixed.account_id is not None:
        # hinterlegtes Konto: nur Zahlungen von diesem Konto (Abweichungen lassen sich fest verknüpfen)
        query = query.where(L.account_id == fixed.account_id)
    if fixed.match_text:
        pattern = "%" + fixed.match_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(
            or_(
                Transaction.description.ilike(pattern, escape="\\"),
                Transaction.counterparty.ilike(pattern, escape="\\"),
            )
        )
    return list(session.execute(query))


def _linked_lines(session: Session, user_id: int, first: date):
    """Fest verknüpfte Zahlungen: alle verknüpften Zeilen des Profils und die des Monats je Fixkost."""
    rows = session.execute(
        select(FixedCostPayment.fixed_cost_id, FixedCostPayment.due_month, L.transaction_id, L.split_id,
               L.amount, L.booking_date, L.excluded_at, L.kind)
        .select_from(FixedCostPayment)
        .join(transaction_line, and_(L.transaction_id == FixedCostPayment.transaction_id,
                                     L.split_id.is_not_distinct_from(FixedCostPayment.split_id)))
        .where(FixedCostPayment.user_id == user_id)
    ).all()
    taken = {(r.transaction_id, r.split_id) for r in rows}
    # Eine Verknüpfung zählt nur, solange die Zeile noch eine reguläre Abbuchung ist (Buchung kann sich ändern).
    this_month = {r.fixed_cost_id: r for r in rows
                  if r.due_month == first and r.excluded_at is None and r.amount < 0 and r.kind == "regular"}
    return taken, this_month


def _fixed_items(session: Session, user_id: int, first: date, last: date, today: date):
    """Fixkosten des Monats mit erkannter Zahlung; jede Buchungszeile zählt nur für eine Fixkost.

    Fest verknüpfte Zahlungen haben Vorrang; sonst wird über Kategorie/Suchtext erkannt.
    Zweiter Wert: Summe der Zahlungen, die im Monat gebucht sind. Dritter Wert: Rücklagen
    nicht-monatlicher Fixkosten, die in diesem Monat nicht fällig sind (nur zur Anzeige)."""
    items, paid_actual, reserves = [], ZERO, []
    consumed, linked = _linked_lines(session, user_id, first)
    active = _active_fixed_costs(session, user_id, first, last)
    history = _amount_history(session, [f.id for f in active])
    for fixed in active:
        if not is_due_in_month(fixed, first):
            reserves.append({
                "fixed_cost_id": fixed.id,
                "name": fixed.name,
                "monthly_reserve": (amount_for(fixed, first, history) / fixed.interval_months).quantize(
                    Decimal("0.01")),
                "next_due_date": due_in_month(next_due_month(fixed, first), fixed.due_day),
            })
    for fixed in (f for f in active if is_due_in_month(f, first)):
        match = linked.get(fixed.id)
        is_linked = match is not None
        if match is None:
            match = next(
                (c for c in _payment_candidates(session, user_id, fixed, first, last)
                 if (c.transaction_id, c.split_id) not in consumed),
                None,
            )
        if match is not None:
            consumed.add((match.transaction_id, match.split_id))
            if first <= match.booking_date <= last:
                paid_actual += -match.amount
        due = due_in_month(first, fixed.due_day)
        items.append({
            "kind": "fixed",
            "ref_id": fixed.id,
            "name": fixed.name,
            "amount": amount_for(fixed, first, history),
            "due_date": due,
            "status": _status(due, match is not None, today),
            "paid_amount": -match.amount if match is not None else None,
            "paid_on": match.booking_date if match is not None else None,
            "linked": is_linked,
        })
    return items, paid_actual, reserves


def _loan_items(session: Session, user_id: int, first: date, last: date, today: date):
    """Im Monat fällige Kreditraten (ausgesetzte nicht); bezahlte mit tatsächlicher Zahlung."""
    rows = session.execute(
        select(LoanScheduleEntry, Loan, LoanPayment)
        .join(Loan, Loan.id == LoanScheduleEntry.loan_id)
        .outerjoin(LoanPayment, LoanPayment.id == LoanScheduleEntry.payment_id)
        .where(
            Loan.user_id == user_id,
            LoanScheduleEntry.due_date.between(first, last),
            LoanScheduleEntry.status != ScheduleStatus.SKIPPED,
        )
        .order_by(LoanScheduleEntry.due_date, LoanScheduleEntry.id)
    ).all()
    items = []
    for entry, loan, payment in rows:
        name = session.get(Account, loan.account_id).name
        paid = entry.status == ScheduleStatus.PAID
        items.append({
            "kind": "loan",
            "ref_id": loan.id,
            "name": name,
            "amount": entry.planned_installment,
            "due_date": entry.due_date,
            "status": _status(entry.due_date, paid, today),
            "paid_amount": (payment.interest + payment.principal + payment.extra) if payment else None,
            "paid_on": payment.booking_date if payment else None,
        })
    return items


def _loan_principal_paid(session: Session, user_id: int, first: date, last: date) -> Decimal:
    """Tilgungsanteile gebuchter Raten im Monat – als Umbuchung nicht in den Ausgaben, aber ein Abfluss."""
    value = session.execute(
        select(func.coalesce(func.sum(LoanPayment.principal), 0))
        .join(Loan, Loan.id == LoanPayment.loan_id)
        .where(Loan.user_id == user_id, LoanPayment.booking_date.between(first, last))
    ).scalar_one()
    return Decimal(value)


def _flows(session: Session, user_id: int, first: date, last: date) -> tuple[Decimal, Decimal, Decimal]:
    """(Einnahmen, unkategorisierte Eingänge, Ausgaben gesamt) des Monats."""
    base = and_(
        L.user_id == user_id,
        L.kind == "regular",
        L.excluded_at.is_(None),
        L.booking_date.between(first, last),
    )
    lines = select(L.amount, Category.type.label("category_type")).select_from(
        transaction_line.outerjoin(Category, Category.id == L.category_id)
    ).where(base)
    income = unc_in = spent = ZERO
    for amount, category_type in session.execute(lines):
        if category_type == "income":
            income += amount
        elif category_type == "expense":
            spent -= amount
        elif amount > 0:
            unc_in += amount
        else:
            spent -= amount
    return income, unc_in, spent


def month_budget(session: Session, user_id: int, month: date, today: date) -> dict:
    first = month_start(month)
    last = month_end(first)
    fixed_items, fixed_paid_actual, reserves = _fixed_items(session, user_id, first, last, today)
    loan_items = _loan_items(session, user_id, first, last, today)
    items = sorted(fixed_items + loan_items, key=lambda i: (i["due_date"], i["kind"], i["name"]))

    income, unc_in, spent = _flows(session, user_id, first, last)
    # Bezahlte Posten mit dem tatsächlichen Betrag, offene mit dem Planbetrag (Reservierung)
    fixed_total = sum(
        (i["paid_amount"] if i["status"] == "paid" and i["paid_amount"] is not None else i["amount"] for i in items),
        ZERO,
    )
    # Tatsächliche Abflüsse des Monats, abzüglich derer, die schon als bezahlter Posten zählen
    outflow = spent + _loan_principal_paid(session, user_id, first, last)
    loan_paid_here = sum(
        (i["paid_amount"] for i in loan_items
         if i["status"] == "paid" and i["paid_on"] is not None and first <= i["paid_on"] <= last),
        ZERO,
    )
    variable = outflow - fixed_paid_actual - loan_paid_here
    available = income - fixed_total - variable

    if first <= today <= last:
        days_left = (last - today).days + 1
    else:
        days_left = 0 if today > last else (last - first).days + 1
    per_day = (available / days_left).quantize(Decimal("0.01")) if days_left and available > 0 else None
    return {
        "month": first,
        "as_of": today,
        "income": income,
        "uncategorized_in": unc_in,
        "fixed_total": fixed_total,
        "fixed_paid": sum((i["paid_amount"] or ZERO for i in items if i["status"] == "paid"), ZERO),
        "variable_spent": variable,
        "available": available,
        "days_left": days_left,
        "available_per_day": per_day,
        "items": items,
        "reserves": reserves,
    }


# --- Wanddisplay -----------------------------------------------------------------


def wall_view(session: Session, today: date, generated_at, upcoming_limit: int = 6) -> dict:
    """Gemeinsamer Überblick über alle Profile – nur Summen und Fälligkeiten, keine Buchungen."""
    users = list(session.exec(select(User).order_by(func.lower(User.name), User.id)))
    profiles = []
    for user in users:
        budget = month_budget(session, user.id, today, today)
        open_items = [i for i in budget["items"] if i["status"] != "paid"]
        profiles.append({
            "profile_id": user.id,
            "name": user.name,
            "available": budget["available"],
            "income": budget["income"],
            "fixed_total": budget["fixed_total"],
            "variable_spent": budget["variable_spent"],
            "available_per_day": budget["available_per_day"],
            # alle Fixkosten und Raten des Monats mit Status – Grundlage der Zeitleiste
            "timeline": budget["items"],
            "upcoming": open_items[:upcoming_limit],
            "open_items": len(open_items),
        })

    loans = []
    names = {u.id: u.name for u in users}
    for loan in session.exec(select(Loan).order_by(Loan.user_id, Loan.id)):
        entries = open_entries(session, loan)
        last_payment = session.exec(
            select(func.max(LoanPayment.booking_date)).where(LoanPayment.loan_id == loan.id)
        ).one()
        loans.append({
            "loan_id": loan.id,
            "profile_id": loan.user_id,
            "profile_name": names.get(loan.user_id, ""),
            "name": session.get(Account, loan.account_id).name,
            "status": loan.status,
            "remaining_debt": remaining_debt(session, loan),
            # offen: Fälligkeit der Schlussrate; getilgt: Tag der letzten Zahlung
            "payoff_date": entries[-1].due_date if entries else last_payment,
            "remaining_installments": len(entries),
            "next_due_date": entries[0].due_date if entries else None,
            "next_installment": entries[0].planned_installment if entries else None,
        })
    return {
        "generated_at": generated_at,
        "month": month_start(today),
        "as_of": today,
        "days_left": (month_end(month_start(today)) - today).days + 1,
        "profiles": profiles,
        "loans": loans,
    }
