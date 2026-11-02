from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.deps import CurrentUser, SessionDep
from app.schemas.filters import TransactionFilter
from app.schemas.transaction import (
    TransactionCreate,
    TransactionExclude,
    TransactionPage,
    TransactionRead,
    TransactionUpdate,
    TransferCreate,
    TransferRead,
)
from app.services import transactions as service

router = APIRouter(tags=["Buchungen"])


@router.get("/transactions", response_model=TransactionPage)
def list_transactions(
    session: SessionDep,
    user: CurrentUser,
    filters: Annotated[TransactionFilter, Query()],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Buchungen, neueste zuerst (`booking_date`, dann `id` absteigend)."""
    items, total = service.list_transactions(session, user, filters, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/transactions", response_model=TransactionRead, status_code=201)
def create_transaction(data: TransactionCreate, session: SessionDep, user: CurrentUser):
    """Manuelle Buchung. Negative Beträge sind Abflüsse; Erstattungen dürfen in
    Ausgabenkategorien positiv sein. Mit `splits` wird die Buchung aufgeteilt."""
    tx = service.create_transaction(session, user, data)
    session.commit()
    return tx


@router.get("/transactions/{transaction_id}", response_model=TransactionRead)
def get_transaction(transaction_id: int, session: SessionDep, user: CurrentUser):
    return service.get_transaction(session, user, transaction_id)


@router.patch("/transactions/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    transaction_id: int, data: TransactionUpdate, session: SessionDep, user: CurrentUser
):
    tx = service.get_transaction(session, user, transaction_id)
    service.update_transaction(session, user, tx, data.changes())
    session.commit()
    return tx


@router.delete("/transactions/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: int, session: SessionDep, user: CurrentUser):
    """Nur manuelle Buchungen; importierte werden ausgeschlossen (409)."""
    service.delete_transaction(session, service.get_transaction(session, user, transaction_id))
    session.commit()
    return Response(status_code=204)


@router.post("/transactions/{transaction_id}/exclude", response_model=TransactionRead)
def exclude_transaction(
    transaction_id: int, data: TransactionExclude, session: SessionDep, user: CurrentUser
):
    """Importierte Buchung aus Salden/Berichten ausschließen – die Importidentität bleibt."""
    tx = service.set_excluded(session, service.get_transaction(session, user, transaction_id), data.reason)
    session.commit()
    return tx


@router.post("/transactions/{transaction_id}/include", response_model=TransactionRead)
def include_transaction(transaction_id: int, session: SessionDep, user: CurrentUser):
    tx = service.set_excluded(session, service.get_transaction(session, user, transaction_id), None)
    session.commit()
    return tx


@router.post("/transfers", response_model=TransferRead, status_code=201)
def create_transfer(data: TransferCreate, session: SessionDep, user: CurrentUser):
    """Umbuchung zwischen eigenen Konten (auch bankübergreifend): beide Seiten atomar."""
    outgoing, incoming = service.create_transfer(session, user, data)
    session.commit()
    return {"outgoing": outgoing, "incoming": incoming}
