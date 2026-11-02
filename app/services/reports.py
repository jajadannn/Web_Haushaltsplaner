"""Berichte – alle über die View `transaction_line` (Split-Zeilen bzw. ungeteilte Buchungen).

Fachliche Regeln:
- Umbuchungen (auch Kredit-Tilgungen) sind weder Einnahme noch Ausgabe.
- Erstattungen werden in ihrer Kategorie verrechnet (−100 und +30 → 70 Nettoausgabe).
- Unkategorisierte Beträge erscheinen gesondert und verschwinden nie.
- Ausgeschlossene Buchungen zählen nicht; archivierte Konten bleiben enthalten.
- Salden gelten am Ende des Stichtags; vor dem Anfangssaldo-Stichtag gibt es keinen Saldo.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, and_, case, cast, func, literal, select, text
from sqlmodel import Session

from app.models import Account, Category, Institution, Loan, LoanPayment, Transaction, User, transaction_line
from app.services.balances import balances
from app.services.categories import get_system_category
from app.services.loans.core import open_entries, remaining_debt

ZERO = Decimal("0.00")
L = transaction_line.c


def _lines(user: User, date_from: date, date_to: date):
    """Reguläre, gültige Zeilen im Zeitraum (inkl. Grenzen) mit Kategorietyp."""
    return (
        select(
            L.amount, L.category_id, L.booking_date, Category.type.label("category_type"), L.transaction_id
        )
        .select_from(transaction_line.outerjoin(Category, Category.id == L.category_id))
        .where(
            L.user_id == user.id,
            L.kind == "regular",
            L.excluded_at.is_(None),
            L.booking_date.between(date_from, date_to),
        )
    )


def _flows(rows) -> dict:
    """Einnahmen/Ausgaben je Kategorietyp; Geldflüsse (cash_in/out) je Buchung, nicht je Split-Zeile."""
    income = expenses = unc_in = unc_out = cash_in = cash_out = ZERO
    per_transaction: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for amount, _category_id, _booking_date, category_type, transaction_id in rows:
        per_transaction[transaction_id] += amount
        if category_type == "income":
            income += amount
        elif category_type == "expense":
            expenses -= amount
        elif amount > 0:
            unc_in += amount
        else:
            unc_out -= amount
    for total in per_transaction.values():
        if total > 0:
            cash_in += total
        else:
            cash_out -= total
    return {
        "income": income,
        "expenses": expenses,
        "uncategorized_in": unc_in,
        "uncategorized_out": unc_out,
        "net": income - expenses + unc_in - unc_out,
        "cash_in": cash_in,
        "cash_out": cash_out,
    }


def _money(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def _month(d: date) -> date:
    return d.replace(day=1)


def summary(session: Session, user: User, date_from: date, date_to: date) -> dict:
    accounts = list(session.execute(select(Account).where(Account.user_id == user.id).order_by(Account.id)).scalars())
    names = {i.id: i.name for i in session.execute(select(Institution).where(Institution.user_id == user.id)).scalars()}
    at_end = balances(session, user.id, date_to)
    account_rows, by_institution = [], defaultdict(lambda: ZERO)
    assets = liabilities = ZERO
    for account in accounts:
        balance = at_end[account.id]
        if balance is not None:
            by_institution[account.institution_id] += balance
            if balance >= 0:
                assets += balance
            else:
                liabilities += balance
        account_rows.append(
            {
                "account_id": account.id,
                "name": account.name,
                "type": account.type,
                "institution_id": account.institution_id,
                "archived": account.archived_at is not None,
                "balance": balance,
                "history_incomplete": account.opening_balance_date > date_from,
            }
        )
    rows = list(session.execute(_lines(user, date_from, date_to)))
    monthly = defaultdict(list)
    for row in rows:
        monthly[_month(row.booking_date)].append(row)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "accounts": account_rows,
        "institutions": [
            {"institution_id": iid, "name": names.get(iid, "Ohne Bank"), "balance": total}
            for iid, total in sorted(by_institution.items(), key=lambda x: (x[0] is None, x[0] or 0))
        ],
        "assets": assets,
        "liabilities": liabilities,
        "net_worth": assets + liabilities,
        "movements": _flows(rows),
        "months": [{"month": m, **_flows(monthly[m])} for m in _months(date_from, date_to)],
    }


def _months(date_from: date, date_to: date) -> list[date]:
    months, current = [], _month(date_from)
    while current <= date_to:
        months.append(current)
        current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
    return months


def _root_map(session: Session, user: User) -> dict[int, int]:
    """Kategorie → oberste Elternkategorie (rekursiv)."""
    tree = (
        select(Category.id.label("id"), Category.id.label("root"))
        .where(Category.user_id == user.id, Category.parent_id.is_(None))
        .cte("tree", recursive=True)
    )
    tree = tree.union_all(select(Category.id, tree.c.root).where(Category.parent_id == tree.c.id))
    return dict(session.execute(select(tree.c.id, tree.c.root)).all())


def categories(session: Session, user: User, date_from: date, date_to: date, cat_type: str) -> dict:
    """Je Kategorie Brutto, Erstattungen und Netto; Elternkategorien enthalten ihre Unterkategorien.

    Anteile (`share`) nur für positive Nettowerte – negative oder leere Summen ergeben
    keine sinnvollen Tortenstücke (`share = null`).
    """
    sign = Decimal(-1) if cat_type == "expense" else Decimal(1)
    own: dict[int, dict] = defaultdict(lambda: {"gross": ZERO, "refunds": ZERO})
    uncategorized = ZERO
    for amount, category_id, _d, category_type, _tx in session.execute(_lines(user, date_from, date_to)):
        value = amount * sign  # Ausgaben positiv rechnen
        if category_type == cat_type:
            bucket = own[category_id]
            if value > 0:
                bucket["gross"] += value
            else:
                bucket["refunds"] -= value
        elif category_id is None and value > 0:
            uncategorized += value

    cats = {
        c.id: c
        for c in session.execute(
            select(Category).where(Category.user_id == user.id, Category.type == cat_type)
        ).scalars()
    }
    roots = _root_map(session, user)
    totals: dict[int, dict] = defaultdict(lambda: {"gross": ZERO, "refunds": ZERO})
    for category_id, values in own.items():
        ancestors = {category_id}
        current = cats.get(category_id)
        while current is not None and current.parent_id is not None:  # jede Zeile genau einmal je Ebene
            ancestors.add(current.parent_id)
            current = cats.get(current.parent_id)
        for cid in ancestors:
            totals[cid]["gross"] += values["gross"]
            totals[cid]["refunds"] += values["refunds"]

    top_net = sum(
        (max(t["gross"] - t["refunds"], ZERO) for cid, t in totals.items() if cats[cid].parent_id is None), ZERO
    )
    items = []
    for cid, total in totals.items():
        category = cats[cid]
        net = total["gross"] - total["refunds"]
        own_values = own.get(cid, {"gross": ZERO, "refunds": ZERO})
        items.append(
            {
                "category_id": cid,
                "name": category.name,
                "parent_id": category.parent_id,
                "root_id": roots.get(cid, cid),
                "gross": total["gross"],
                "refunds": total["refunds"],
                "net": net,
                "own_net": own_values["gross"] - own_values["refunds"],
                "share": (net / top_net).quantize(Decimal("0.0001")) if net > 0 and top_net > 0 else None,
            }
        )
    items.sort(key=lambda i: (i["parent_id"] is not None, -i["net"], i["name"].casefold()))
    return {
        "date_from": date_from,
        "date_to": date_to,
        "type": cat_type,
        "items": items,
        "total_net": sum((i["net"] for i in items if i["parent_id"] is None), ZERO),
        # Bezugsgröße der Anteile: Summe der positiven Nettowerte der Hauptkategorien
        "share_basis": top_net,
        "uncategorized": uncategorized,
    }


def trends(session: Session, user: User, months: int, until: date, category_id: int | None = None) -> dict:
    """Monatswerte lückenlos (auch Monate ohne Buchungen); Abdeckung ist im MVP unbekannt."""
    end = _month(until)
    start = date(end.year, end.month, 1)
    for _ in range(months - 1):
        start = date(start.year - (start.month == 1), (start.month - 2) % 12 + 1, 1)
    series = (
        select(cast(func.generate_series(start, end, text("interval '1 month'")), Date).label("month"))
        .subquery()
    )
    month_of = cast(func.date_trunc("month", L.booking_date), Date)
    category_filter = literal(True)
    if category_id is not None:
        from app.services.transactions import category_with_descendants

        category_filter = L.category_id.in_(category_with_descendants(session, user.id, category_id))
    lines = (
        select(month_of.label("month"), L.amount, Category.type.label("category_type"), L.category_id)
        .select_from(transaction_line.outerjoin(Category, Category.id == L.category_id))
        .where(
            L.user_id == user.id,
            L.kind == "regular",
            L.excluded_at.is_(None),
            L.booking_date >= start,
            L.booking_date <= until,  # angefangener Monat nur bis einschließlich `until`
            category_filter,
        )
        .subquery()
    )
    total = lambda condition: func.coalesce(func.sum(case((condition, lines.c.amount))), 0)  # noqa: E731
    query = (
        select(
            series.c.month,
            total(lines.c.category_type == "income"),
            -total(lines.c.category_type == "expense"),
            -total(and_(lines.c.category_id.is_(None), lines.c.amount < 0)),
            total(and_(lines.c.category_id.is_(None), lines.c.amount > 0)),
        )
        .select_from(series.outerjoin(lines, lines.c.month == series.c.month))
        .group_by(series.c.month)
        .order_by(series.c.month)
    )
    items = []
    for month, income, expenses, unc_out, unc_in in session.execute(query):
        income, expenses, unc_out, unc_in = (_money(v) for v in (income, expenses, unc_out, unc_in))
        items.append(
            {
                "month": month,
                "income": income,
                "expenses": expenses,
                "uncategorized_out": unc_out,
                "uncategorized_in": unc_in,
                "net": income - expenses + unc_in - unc_out,
                "coverage": "unknown",
            }
        )
    return {"months": items, "category_id": category_id}


def loans(session: Session, user: User, until: date, months: int = 12) -> dict:
    """Restschuld je Kredit am Monatsende, Zinsen je Jahr und monatliche Belastung."""
    items, monthly_burden = [], ZERO
    month_ends = []
    current = _month(until)
    for _ in range(months):
        nxt = date(current.year + current.month // 12, current.month % 12 + 1, 1)
        month_ends.append(date.fromordinal(nxt.toordinal() - 1))
        current = date(current.year - (current.month == 1), (current.month - 2) % 12 + 1, 1)
    month_ends.reverse()
    month_ends[-1] = min(month_ends[-1], until)  # angefangener Monat: Stand am Tag `until`
    interest_category = get_system_category(session, user.id, "loan_interest").id
    for loan in session.execute(select(Loan).where(Loan.user_id == user.id).order_by(Loan.id)).scalars():
        account = session.get(Account, loan.account_id)
        entries = open_entries(session, loan)
        if entries and loan.status == "active":
            monthly_burden += entries[0].planned_installment
        interest_by_year: dict[int, Decimal] = defaultdict(lambda: ZERO)
        paid = session.execute(
            select(func.extract("year", LoanPayment.booking_date), func.sum(LoanPayment.interest))
            .where(LoanPayment.loan_id == loan.id, LoanPayment.booking_date <= until)
            .group_by(func.extract("year", LoanPayment.booking_date))
        )
        charged = session.execute(  # direkt dem Kreditkonto belastete Zinsen
            select(func.extract("year", Transaction.booking_date), -func.sum(Transaction.amount))
            .where(
                Transaction.account_id == loan.account_id,
                Transaction.category_id == interest_category,
                Transaction.excluded_at.is_(None),
                Transaction.booking_date <= until,
            )
            .group_by(func.extract("year", Transaction.booking_date))
        )
        for year, value in [*paid, *charged]:
            interest_by_year[int(year)] += Decimal(value)
        items.append(
            {
                "loan_id": loan.id,
                "name": account.name,
                "status": loan.status,
                "remaining_debt": remaining_debt(session, loan),
                "next_installment": entries[0].planned_installment if entries else None,
                "remaining_by_month": [
                    {"month_end": d, "remaining_debt": remaining_debt(session, loan, d)} for d in month_ends
                ],
                "interest_paid_by_year": [
                    {"year": year, "interest": _money(value)} for year, value in sorted(interest_by_year.items())
                ],
            }
        )
    return {"loans": items, "monthly_burden": monthly_burden}
