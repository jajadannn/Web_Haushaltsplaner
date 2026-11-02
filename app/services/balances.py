"""Kontostände werden immer berechnet, nie gespeichert.

Saldo(Ende Tag D) = Anfangssaldo + alle nicht ausgeschlossenen Buchungen vom Stichtag bis D.
Vor dem Stichtag ist kein Saldo verfügbar (None).
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import and_
from sqlmodel import Session, func, select

from app.models import Account
from app.models.transaction import Transaction


def balances(
    session: Session, user_id: int, as_of: date, account_ids: Iterable[int] | None = None
) -> dict[int, Decimal | None]:
    """Salden aller (bzw. der angegebenen) Konten mit einer einzigen Aggregatabfrage."""
    booked = func.coalesce(
        func.sum(Transaction.amount).filter(
            and_(
                Transaction.booking_date >= Account.opening_balance_date,
                Transaction.booking_date <= as_of,
                Transaction.excluded_at.is_(None),
            )
        ),
        0,
    )
    query = (
        select(Account.id, Account.opening_balance, Account.opening_balance_date, booked)
        .select_from(Account)
        .outerjoin(Transaction, Transaction.account_id == Account.id)
        .where(Account.user_id == user_id)
        .group_by(Account.id)
    )
    if account_ids is not None:
        query = query.where(Account.id.in_(list(account_ids)))
    return {
        account_id: None if as_of < opening_date else opening + total
        for account_id, opening, opening_date, total in session.exec(query)
    }
