"""Belastbare Vorschau (Phase 5).

- Fehlende/ungewöhnliche Zahlungen (Idee 05): nur innerhalb importierter Zeiträume und erst nach
  einer Toleranz von fünf Bankarbeitstagen. Formulierung „noch nicht in den importierten Buchungen“ –
  nie die Behauptung, eine Zahlung sei sicher ausgeblieben; nie wird etwas gelöscht.
- Erwartete Einnahmen (Idee 16): Gehalt, Rente … als Planwert für die Vorschau, nie als Buchung.
- Kontovorschau (Idee 17): heutiger Kontostand plus offene Fixkosten, Kreditraten und erwartete
  Einnahmen bis zu einem Datum; erwartete Ereignisse sind als solche gekennzeichnet.
- Jahreskosten (Idee 18): ein größerer Betrag vor knapp einem Jahr ohne Fixkost ist ein schwacher
  Hinweis auf einen Jahresposten.
"""

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from app import clock
from app.errors import Invalid
from app.models import (
    Account,
    AccountType,
    Category,
    ExpectedIncome,
    FixedCost,
    Loan,
    LoanScheduleEntry,
    ScheduleStatus,
    Suggestion,
    SuggestionKind,
    Transaction,
    TransactionKind,
    User,
)
from app.schemas.budget import FixedCostCreate
from app.services import analysis, budget, calendar_de, changes, coverage, recurring, suggestions
from app.services.balances import balances
from app.services.common import apply_changes, flush_or_conflict, get_owned
from app.services.suggestions import Found, Handler

ZERO = Decimal("0.00")
TOLERANCE_BUSINESS_DAYS = 5


# --- Erwartete Einnahmen: Verwaltung -------------------------------------------------------------

_UNIQUE = {"uq_expected_income_user_id_name": "Eine erwartete Einnahme mit diesem Namen existiert bereits"}


def list_incomes(session: Session, user: User) -> list[ExpectedIncome]:
    return list(session.exec(select(ExpectedIncome).where(ExpectedIncome.user_id == user.id)
                             .order_by(ExpectedIncome.due_day, ExpectedIncome.name)))


def get_income(session: Session, user: User, income_id: int) -> ExpectedIncome:
    return get_owned(session, ExpectedIncome, income_id, user.id, "Erwartete Einnahme")


def _check_income(session: Session, user: User, values: dict) -> None:
    if values.get("account_id") is not None:
        account = get_owned(session, Account, values["account_id"], user.id, "Konto")
        if account.type == AccountType.LOAN:
            raise Invalid("Einnahmen gehen nicht auf ein Kreditkonto", code="income_account_type")
    if values.get("category_id") is not None:
        category = get_owned(session, Category, values["category_id"], user.id, "Kategorie")
        if category.type != "income":
            raise Invalid("Erwartete Einnahmen brauchen eine Einnahmen-Kategorie", code="income_category_type")
    if values.get("interval_months", 1) != 1 and values.get("first_due_date") is None:
        raise Invalid("first_due_date angeben, wenn die Einnahme nicht monatlich ist", code="first_due_date_required")


def create_income(session: Session, user: User, values: dict) -> ExpectedIncome:
    _check_income(session, user, values)
    income = ExpectedIncome(user_id=user.id, **values)
    session.add(income)
    flush_or_conflict(session, _UNIQUE)
    return income


def update_income(session: Session, user: User, income: ExpectedIncome, changes_: dict) -> ExpectedIncome:
    merged = {k: getattr(income, k) for k in ("account_id", "category_id", "interval_months", "first_due_date")}
    _check_income(session, user, merged | changes_)
    apply_changes(income, changes_)
    flush_or_conflict(session, _UNIQUE)
    return income


def delete_income(session: Session, income: ExpectedIncome) -> None:
    session.delete(income)
    session.flush()


def _income_due(income: ExpectedIncome, first: date) -> bool:
    if income.interval_months == 1 or income.first_due_date is None:
        return True
    diff = budget.months_between(income.first_due_date, first)
    return diff >= 0 and diff % income.interval_months == 0


def _income_received(session: Session, income: ExpectedIncome, first: date, last: date) -> bool:
    query = select(Transaction.id).where(
        Transaction.user_id == income.user_id, Transaction.amount > 0, Transaction.excluded_at.is_(None),
        Transaction.kind == TransactionKind.REGULAR, Transaction.booking_date.between(first, last),
    )
    if income.account_id is not None:
        query = query.where(Transaction.account_id == income.account_id)
    if income.category_id is not None:
        query = query.where(Transaction.category_id == income.category_id)
    elif income.match_text:
        pattern = f"%{income.match_text}%"
        query = query.where(Transaction.counterparty.ilike(pattern) | Transaction.description.ilike(pattern))
    else:
        query = query.where(Transaction.amount >= income.amount * Decimal("0.8"))
    return session.exec(query).first() is not None


# --- 17 Kontovorschau ----------------------------------------------------------------------------


def _months(start: date, end: date):
    current = budget.month_start(start)
    while current <= end:
        yield current
        current = date(current.year + current.month // 12, current.month % 12 + 1, 1)


def forecast(session: Session, user: User, account_id: int, until: date) -> dict:
    account = get_owned(session, Account, account_id, user.id, "Konto")
    today = clock.today()
    if until <= today:
        raise Invalid("Das Vorschau-Datum muss in der Zukunft liegen", code="forecast_until_past")
    if (until - today).days > 400:
        raise Invalid("Höchstens 400 Tage Vorschau", code="forecast_too_long")
    start_balance = balances(session, user.id, today, [account.id])[account.id] or ZERO
    events = []
    for first in _months(today, until):
        items = {(i["kind"], i["ref_id"]): i for i in budget.month_budget(session, user.id, first, today)["items"]}
        for fixed in session.exec(select(FixedCost).where(FixedCost.user_id == user.id, FixedCost.active,
                                                          FixedCost.account_id == account.id)):
            item = items.get(("fixed", fixed.id))
            if item is None or item["status"] == "paid" or not (today < item["due_date"] <= until):
                continue
            events.append({"date": item["due_date"], "name": fixed.name, "amount": -item["amount"],
                           "kind": "fixed_cost", "expected": True, "ref_id": fixed.id})
        last = budget.month_end(first)
        for income in session.exec(select(ExpectedIncome).where(
                ExpectedIncome.user_id == user.id, ExpectedIncome.active, ExpectedIncome.account_id == account.id)):
            due = budget.due_in_month(first, income.due_day)
            if not _income_due(income, first) or not (today < due <= until):
                continue
            if _income_received(session, income, first, last):
                continue
            event = {"date": due, "name": income.name, "amount": income.amount, "kind": "expected_income",
                     "expected": True, "ref_id": income.id}
            if income.amount_min is not None and income.amount_max is not None:
                event["range"] = [income.amount_min, income.amount_max]
            events.append(event)
    entries = session.exec(
        select(LoanScheduleEntry, Loan)
        .join(Loan, Loan.id == LoanScheduleEntry.loan_id)
        .where(Loan.user_id == user.id, Loan.payment_account_id == account.id,
               LoanScheduleEntry.status == ScheduleStatus.PLANNED,
               LoanScheduleEntry.due_date > today, LoanScheduleEntry.due_date <= until)
    ).all()
    for entry, loan in entries:
        name = session.get(Account, loan.account_id).name
        events.append({"date": entry.due_date, "name": f"Rate {name}", "amount": -entry.planned_installment,
                       "kind": "loan_installment", "expected": True, "ref_id": loan.id})
    events.sort(key=lambda e: (e["date"], e["amount"] > 0, e["name"]))
    balance, lowest = start_balance, {"date": today, "balance": start_balance}
    for event in events:
        balance += event["amount"]
        event["balance_after"] = balance
        if balance < lowest["balance"]:
            lowest = {"date": event["date"], "balance": balance}
    return {"account_id": account.id, "as_of": today, "until": until, "start_balance": start_balance,
            "events": events, "end_balance": balance, "lowest": lowest}


# --- 05 Fehlende und ungewöhnliche Zahlungen -----------------------------------------------------


def _accounts_to_check(session: Session, user: User, fixed: FixedCost) -> list[int] | None:
    """Konten, deren Importe die Zahlung zeigen müssten; None = nur manuell gepflegte Konten."""
    if fixed.account_id is not None:
        return [fixed.account_id] if coverage.has_imports(session, fixed.account_id) else None
    accounts = [a.id for a in session.exec(select(Account).where(Account.user_id == user.id,
                                                                Account.type != AccountType.LOAN))]
    imported = [a for a in accounts if coverage.has_imports(session, a)]
    return imported or None


def detect_payment_issues(session: Session, user: User, today: date) -> tuple[list[Found], list[Found]]:
    missing, unusual = [], []
    first_this = budget.month_start(today)
    previous = budget.month_start(first_this - timedelta(days=1))
    for first in (previous, first_this):
        last = budget.month_end(first)
        items = {i["ref_id"]: i for i in budget.month_budget(session, user.id, first, today)["items"]
                 if i["kind"] == "fixed"}
        for fixed in session.exec(select(FixedCost).where(FixedCost.user_id == user.id, FixedCost.active)):
            item = items.get(fixed.id)
            if item is None:
                continue
            due = calendar_de.next_business_day(item["due_date"])
            deadline = calendar_de.add_business_days(due, TOLERANCE_BUSINESS_DAYS)
            if item["status"] != "paid" and deadline < today:
                accounts = _accounts_to_check(session, user, fixed)
                if accounts and any(coverage.covers(session, a, item["due_date"], deadline) for a in accounts):
                    missing.append(Found(
                        fingerprint=f"missing:{fixed.id}|{first.isoformat()}",
                        payload={"fixed_cost_id": fixed.id, "name": fixed.name, "amount": item["amount"],
                                 "due_date": item["due_date"], "month": first},
                        evidence={"checked_until": deadline},
                        reason=f"Die erwartete Zahlung „{fixed.name}“ (fällig {item['due_date']:%d.%m.%Y}) ist in den "
                               f"bis {deadline:%d.%m.%Y} importierten Buchungen noch nicht enthalten.",
                        priority=1,
                    ))
            candidates = [c for c in budget._payment_candidates(session, user.id, fixed, first, last)
                          if abs(-c.amount - item["amount"]) <= item["amount"] * Decimal("0.05")]
            if len(candidates) >= 2:
                unusual.append(Found(
                    fingerprint=f"duplicate:{fixed.id}|{first.isoformat()}",
                    payload={"type": "duplicate", "fixed_cost_id": fixed.id, "name": fixed.name, "month": first,
                             "amount": item["amount"]},
                    evidence={"transactions": [c.transaction_id for c in candidates]},
                    reason=f"„{fixed.name}“ wurde im {first:%m/%Y} {len(candidates)}× abgebucht – "
                           "bitte prüfen, ob eine Abbuchung doppelt ist (es wird nichts gelöscht).",
                    priority=2,
                ))
            elif item["status"] == "paid" and item["paid_amount"] is not None \
                    and item["paid_amount"] > item["amount"] * Decimal("1.5"):
                unusual.append(Found(
                    fingerprint=f"high:{fixed.id}|{first.isoformat()}",
                    payload={"type": "high", "fixed_cost_id": fixed.id, "name": fixed.name, "month": first,
                             "amount": item["amount"], "paid_amount": item["paid_amount"]},
                    evidence={}, priority=1,
                    reason=f"„{fixed.name}“ kostete im {first:%m/%Y} {item['paid_amount']} € statt {item['amount']} €.",
                ))
    return missing, unusual


def _note(session, user, suggestion, overrides, actor):
    return "note", None  # Hinweis zur Kenntnis genommen


suggestions.register(SuggestionKind.MISSING_PAYMENT, Handler(validate=lambda s, u, x: None, apply=_note))
suggestions.register(SuggestionKind.UNUSUAL_PAYMENT, Handler(validate=lambda s, u, x: None, apply=_note))


def refresh_payment_issues(session: Session, user: User, today: date) -> dict[str, int]:
    missing, unusual = detect_payment_issues(session, user, today)
    a = suggestions.sync(session, user, SuggestionKind.MISSING_PAYMENT, missing, "missing-v1")
    b = suggestions.sync(session, user, SuggestionKind.UNUSUAL_PAYMENT, unusual, "unusual-v1")
    return {k: a[k] + b[k] for k in a}


# --- 16 Erkennung erwarteter Einnahmen -----------------------------------------------------------


def detect_incomes(session: Session, user: User, today: date) -> list[Found]:
    income_categories = {c.id for c in session.exec(select(Category).where(Category.user_id == user.id,
                                                                           Category.type == "income"))}
    existing = list(session.exec(select(ExpectedIncome).where(ExpectedIncome.user_id == user.id)))
    txs = session.exec(select(Transaction).where(
        Transaction.user_id == user.id, Transaction.amount > 0, Transaction.excluded_at.is_(None),
        Transaction.kind == TransactionKind.REGULAR, Transaction.category_id.in_(income_categories or {0}),
        Transaction.booking_date >= today - timedelta(days=recurring.HISTORY_DAYS),
    )).all()
    groups: dict[str, list[recurring.Line]] = {}
    for tx in txs:
        line = recurring.Line(tx.id, None, tx.amount, tx.booking_date, tx.category_id, tx.account_id,
                              tx.counterparty, tx.counterparty_iban, tx.description or "")
        key = recurring.group_key(line)
        if key:
            groups.setdefault(key, []).append(line)
    found = []
    for key, lines in groups.items():
        lines.sort(key=lambda x: x.booking_date)
        interval = recurring.classify([x.booking_date for x in lines])
        if interval is None or not recurring._still_running(lines[-1].booking_date, interval, today):
            continue
        amounts = [x.amount for x in lines]
        name = (lines[-1].counterparty or lines[-1].description or "Einnahme")[:100]
        if any(e.name == name or (e.match_text and e.match_text.casefold() in name.casefold()) for e in existing):
            continue
        payload = {
            "name": name, "amount": lines[-1].amount, "amount_min": min(amounts), "amount_max": max(amounts),
            "interval_months": interval,
            "due_day": Counter(x.booking_date.day for x in lines).most_common(1)[0][0],
            "first_due_date": lines[0].booking_date if interval > 1 else None,
            "account_id": Counter(x.account_id for x in lines).most_common(1)[0][0],
            "category_id": Counter(x.category_id for x in lines).most_common(1)[0][0],
            "match_text": (lines[-1].counterparty or "")[:100] or None,
        }
        found.append(Found(
            fingerprint=f"income:{key}|{interval}", payload=payload,
            evidence={"transactions": [{"id": x.transaction_id, "date": x.booking_date, "amount": x.amount}
                                       for x in lines]},
            reason=f"{len(lines)} Eingänge von „{name}“, Betrag {min(amounts)}–{max(amounts)} € – für die Vorschau "
                   "als erwartete Einnahme verwenden?",
        ))
    return found


INCOME_FIELDS = ("name", "amount", "amount_min", "amount_max", "interval_months", "due_day", "first_due_date",
                 "account_id", "category_id", "match_text", "active")


def _income_apply(session, user, suggestion: Suggestion, overrides: dict, actor: str):
    values = {k: v for k, v in suggestion.payload.items() if k in INCOME_FIELDS}
    values |= {k: v for k, v in overrides.items() if k in INCOME_FIELDS}
    for key in ("amount", "amount_min", "amount_max"):
        if values.get(key) is not None:
            values[key] = Decimal(str(values[key]))
    if values.get("first_due_date"):
        values["first_due_date"] = date.fromisoformat(str(values["first_due_date"]))
    income = create_income(session, user, values)
    changes.record(session, user.id, income, INCOME_FIELDS, action="create", before=None,
                   suggestion_id=suggestion.id, actor=actor)
    return "expected_income", income.id


suggestions.register(SuggestionKind.INCOME_SERIES, Handler(validate=lambda s, u, x: None, apply=_income_apply))
changes.REVERTERS["expected_income"] = (ExpectedIncome, INCOME_FIELDS, lambda s, obj: s.delete(obj))


def refresh_incomes(session: Session, user: User, today: date) -> dict[str, int]:
    return suggestions.sync(session, user, SuggestionKind.INCOME_SERIES, detect_incomes(session, user, today),
                            "income-v1")


# --- 18 Jahreskosten -----------------------------------------------------------------------------

ANNUAL_MIN_AMOUNT = Decimal("100.00")
LOOKAHEAD_DAYS = 60


def detect_annual(session: Session, user: User, today: date) -> list[Found]:
    lines = recurring.load_lines(session, user.id, today)
    fixed_costs = list(session.exec(select(FixedCost).where(FixedCost.user_id == user.id, FixedCost.active)))
    groups: dict[str, list[recurring.Line]] = {}
    for line in lines:
        key = recurring.group_key(line)
        if key:
            groups.setdefault(key, []).append(line)
    found = []
    for key, items in groups.items():
        recent = [x for x in items if (today - x.booking_date).days < 300]
        last_year = [x for x in items if 300 <= (today - x.booking_date).days <= 400
                     and x.amount >= ANNUAL_MIN_AMOUNT]
        if recent or len(last_year) != 1:
            continue
        line = last_year[0]
        try:
            expected = line.booking_date.replace(year=line.booking_date.year + 1)
        except ValueError:  # 29.02.
            expected = line.booking_date.replace(year=line.booking_date.year + 1, day=28)
        if not (today - timedelta(days=30) <= expected <= today + timedelta(days=LOOKAHEAD_DAYS)):
            continue
        if recurring._covered(fixed_costs, [line], line.amount):
            continue
        name = (line.counterparty or line.description or "Jahresposten")[:100]
        found.append(Found(
            fingerprint=f"annual:{key}|{line.booking_date.isoformat()}",
            payload={"name": name, "amount": line.amount, "interval_months": 12, "due_day": line.booking_date.day,
                     "first_due_date": expected, "expected_date": expected, "category_id": line.category_id,
                     "account_id": line.account_id, "match_text": (line.counterparty or "")[:100] or None},
            evidence={"transactions": [{"id": line.transaction_id, "date": line.booking_date, "amount": line.amount}]},
            reason=f"Am {line.booking_date:%d.%m.%Y} wurden {line.amount} € an „{name}“ gezahlt. Ein jährlicher "
                   f"Posten wäre um den {expected:%d.%m.%Y} wieder fällig – als Jahresposten prüfen? "
                   "(Ein einzelnes Ereignis ist nur ein schwacher Hinweis.)",
        ))
    return found


def _annual_apply(session, user, suggestion: Suggestion, overrides: dict, actor: str):
    allowed = ("name", "amount", "due_day", "first_due_date")
    p = suggestion.payload | {k: v for k, v in overrides.items() if k in allowed}
    fixed = budget.create_fixed_cost(session, user, FixedCostCreate(
        name=p["name"], amount=Decimal(str(p["amount"])), due_day=p["due_day"], interval_months=12,
        first_due_date=date.fromisoformat(str(p["first_due_date"])), category_id=p.get("category_id"),
        account_id=p.get("account_id"), match_text=p.get("match_text") or None,
    ))
    changes.record(session, user.id, fixed, recurring.FIXED_FIELDS, action="create", before=None,
                   suggestion_id=suggestion.id, actor=actor)
    return "fixed_cost", fixed.id


suggestions.register(SuggestionKind.ANNUAL_COST, Handler(validate=lambda s, u, x: None, apply=_annual_apply))


def refresh_annual(session: Session, user: User, today: date) -> dict[str, int]:
    return suggestions.sync(session, user, SuggestionKind.ANNUAL_COST, detect_annual(session, user, today),
                            "annual-v1")


analysis.register("payment_issues", refresh_payment_issues)
analysis.register("incomes", refresh_incomes)
analysis.register("annual_costs", refresh_annual)
