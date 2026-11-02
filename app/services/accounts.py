from datetime import UTC, datetime

from sqlmodel import Session, func, select

from app.errors import Conflict, Invalid
from app.models import Account, AccountType, Institution, Transaction, User
from app.schemas.account import AccountCreate
from app.services.common import apply_changes, flush_or_conflict, get_owned
from app.services.iban import normalize_iban

_UNIQUE = {
    "uq_account_user_id_name": "Ein Konto mit diesem Namen existiert bereits",
    "uq_account_user_id_iban_normalized": "Diese IBAN ist bereits einem Konto zugeordnet",
    "uq_account_institution_id_bank_account_ref": (
        "Diese Kontoreferenz ist bei dieser Bank bereits vergeben"
    ),
}


def _reject_loan_type(account_type: str | None) -> None:
    if account_type == AccountType.LOAN:
        raise Invalid(
            "Kreditkonten werden über /loans verwaltet", code="loan_account_via_loans"
        )


def list_accounts(
    session: Session,
    user: User,
    *,
    institution_id: int | None = None,
    account_type: AccountType | None = None,
    include_archived: bool = False,
) -> list[Account]:
    query = select(Account).where(Account.user_id == user.id)
    if institution_id is not None:
        query = query.where(Account.institution_id == institution_id)
    if account_type is not None:
        query = query.where(Account.type == account_type)
    if not include_archived:
        query = query.where(Account.archived_at.is_(None))
    return list(session.exec(query.order_by(func.lower(Account.name), Account.id)))


def get_account(session: Session, user: User, account_id: int) -> Account:
    return get_owned(session, Account, account_id, user.id, "Konto")


def create_account(session: Session, user: User, data: AccountCreate) -> Account:
    _reject_loan_type(data.type)
    if data.institution_id is not None:
        get_owned(session, Institution, data.institution_id, user.id, "Bank")
    account = Account(
        user_id=user.id,
        institution_id=data.institution_id,
        name=data.name,
        type=data.type,
        currency=data.currency,
        opening_balance=data.opening_balance,
        opening_balance_date=data.opening_balance_date,
        iban_normalized=normalize_iban(data.iban) if data.iban else None,
        bank_account_ref=data.bank_account_ref,
    )
    session.add(account)
    flush_or_conflict(session, _UNIQUE)
    return account


def update_account(session: Session, user: User, account: Account, changes: dict) -> Account:
    if "type" in changes and changes["type"] != account.type:
        _reject_loan_type(account.type)
        _reject_loan_type(changes["type"])
    if account.type == AccountType.LOAN:
        # Restschuld, Stichtag und Plan gehören zusammen – sonst widersprechen sich Saldo und Plan
        locked = sorted(
            k for k in ("opening_balance", "opening_balance_date")
            if k in changes and changes[k] != getattr(account, k)
        )
        if locked:
            raise Invalid(
                "Anfangssaldo und Stichtag eines Kreditkontos werden über /loans verwaltet",
                code="loan_account_via_loans",
                details={"fields": locked},
            )
    if changes.get("institution_id") is not None:
        get_owned(session, Institution, changes["institution_id"], user.id, "Bank")
    if "iban" in changes:
        iban = changes.pop("iban")
        changes["iban_normalized"] = normalize_iban(iban) if iban else None
    new_opening = changes.get("opening_balance_date")
    if new_opening is not None and new_opening > account.opening_balance_date:
        earlier = _transaction_count(session, account, before=new_opening)
        if earlier:
            raise Conflict(
                "Es gibt Buchungen vor dem neuen Stichtag – sie wären im Saldo nicht mehr enthalten",
                code="transactions_before_opening",
                details={"transactions": earlier},
            )
    apply_changes(account, changes)
    flush_or_conflict(session, _UNIQUE)
    return account


def set_archived(session: Session, account: Account, archived: bool) -> Account:
    if archived and account.archived_at is None:
        account.archived_at = datetime.now(UTC)
    elif not archived:
        account.archived_at = None
    session.flush()
    return account


def _transaction_count(session: Session, account: Account, before=None) -> int:
    query = select(func.count()).where(Transaction.account_id == account.id)
    if before is not None:
        query = query.where(Transaction.booking_date < before)
    return session.exec(query).one()


def delete_account(session: Session, account: Account) -> None:
    _reject_loan_type(account.type)
    used = _transaction_count(session, account)
    if used:
        raise Conflict(
            "Konto hat Buchungen – bitte archivieren statt löschen",
            code="account_in_use",
            details={"transactions": used},
        )
    session.delete(account)
    session.flush()
