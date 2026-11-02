from datetime import date

from fastapi import APIRouter, Response

from app import clock
from app.deps import CurrentUser, SessionDep
from app.models import Account, AccountType, User
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate
from app.services import accounts as service
from app.services.balances import balances

router = APIRouter(prefix="/accounts", tags=["Konten"])


def _with_balance(
    session: SessionDep, user: User, accounts: list[Account], as_of: date | None = None
) -> list[AccountRead]:
    as_of = as_of or clock.today()
    values = balances(session, user.id, as_of, [a.id for a in accounts])
    return [
        AccountRead.model_validate(a).model_copy(
            update={"balance": values.get(a.id), "balance_date": as_of}
        )
        for a in accounts
    ]


@router.get("", response_model=list[AccountRead])
def list_accounts(
    session: SessionDep,
    user: CurrentUser,
    institution_id: int | None = None,
    type: AccountType | None = None,
    include_archived: bool = False,
    as_of: date | None = None,
):
    """Konten des Profils mit Saldo am Ende von `as_of` (Standard: heute),
    optional gefiltert nach Bank und Kontotyp."""
    accounts = service.list_accounts(
        session,
        user,
        institution_id=institution_id,
        account_type=type,
        include_archived=include_archived,
    )
    return _with_balance(session, user, accounts, as_of)


@router.post("", response_model=AccountRead, status_code=201)
def create_account(data: AccountCreate, session: SessionDep, user: CurrentUser):
    """Konto anlegen. `opening_balance` ist der Saldo zu Beginn von `opening_balance_date`."""
    account = service.create_account(session, user, data)
    session.commit()
    return _with_balance(session, user, [account])[0]


@router.get("/{account_id}", response_model=AccountRead)
def get_account(account_id: int, session: SessionDep, user: CurrentUser, as_of: date | None = None):
    account = service.get_account(session, user, account_id)
    return _with_balance(session, user, [account], as_of)[0]


@router.patch("/{account_id}", response_model=AccountRead)
def update_account(account_id: int, data: AccountUpdate, session: SessionDep, user: CurrentUser):
    account = service.get_account(session, user, account_id)
    service.update_account(session, user, account, data.changes())
    session.commit()
    return _with_balance(session, user, [account])[0]


@router.post("/{account_id}/archive", response_model=AccountRead)
def archive_account(account_id: int, session: SessionDep, user: CurrentUser):
    """Archivieren statt Löschen: Konto bleibt in historischen Auswertungen enthalten."""
    account = service.set_archived(session, service.get_account(session, user, account_id), True)
    session.commit()
    return _with_balance(session, user, [account])[0]


@router.post("/{account_id}/unarchive", response_model=AccountRead)
def unarchive_account(account_id: int, session: SessionDep, user: CurrentUser):
    account = service.set_archived(session, service.get_account(session, user, account_id), False)
    session.commit()
    return _with_balance(session, user, [account])[0]


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, session: SessionDep, user: CurrentUser):
    service.delete_account(session, service.get_account(session, user, account_id))
    session.commit()
    return Response(status_code=204)
