from fastapi import APIRouter, Response

from app.deps import CurrentUser, SessionDep
from app.schemas.merchant import (
    AliasCreate,
    AliasRead,
    ContractCreate,
    ContractRead,
    MerchantCreate,
    MerchantRead,
    MerchantUpdate,
)
from app.services import merchants as service

router = APIRouter(prefix="/merchants", tags=["Anbieter"])


@router.get("", response_model=list[MerchantRead])
def list_merchants(session: SessionDep, user: CurrentUser):
    """Anbieter, unter denen wechselnde Buchungstexte zusammengefasst werden."""
    return service.list_merchants(session, user)


@router.post("", response_model=MerchantRead, status_code=201)
def create_merchant(data: MerchantCreate, session: SessionDep, user: CurrentUser):
    merchant = service.create_merchant(session, user, data.name, data.kind)
    session.commit()
    return merchant


@router.patch("/{merchant_id}", response_model=MerchantRead)
def update_merchant(merchant_id: int, data: MerchantUpdate, session: SessionDep, user: CurrentUser):
    merchant = service.update_merchant(session, service.get_merchant(session, user, merchant_id), data.changes())
    session.commit()
    return merchant


@router.delete("/{merchant_id}", status_code=204)
def delete_merchant(merchant_id: int, session: SessionDep, user: CurrentUser):
    service.delete_merchant(session, service.get_merchant(session, user, merchant_id))
    session.commit()
    return Response(status_code=204)


@router.get("/{merchant_id}/aliases", response_model=list[AliasRead])
def list_aliases(merchant_id: int, session: SessionDep, user: CurrentUser):
    return service.list_aliases(session, service.get_merchant(session, user, merchant_id))


@router.post("/{merchant_id}/aliases", response_model=AliasRead, status_code=201)
def add_alias(merchant_id: int, data: AliasCreate, session: SessionDep, user: CurrentUser):
    """Merkmal (IBAN, Referenz oder Name), an dem Buchungen des Anbieters erkannt werden."""
    alias = service.add_alias(session, user, service.get_merchant(session, user, merchant_id), data.match_type,
                              data.value, data.contract_id)
    session.commit()
    return alias


@router.delete("/aliases/{alias_id}", status_code=204)
def delete_alias(alias_id: int, session: SessionDep, user: CurrentUser):
    service.delete_alias(session, user, alias_id)
    session.commit()
    return Response(status_code=204)


@router.get("/{merchant_id}/contracts", response_model=list[ContractRead])
def list_contracts(merchant_id: int, session: SessionDep, user: CurrentUser):
    return service.list_contracts(session, service.get_merchant(session, user, merchant_id))


@router.post("/{merchant_id}/contracts", response_model=ContractRead, status_code=201)
def add_contract(merchant_id: int, data: ContractCreate, session: SessionDep, user: CurrentUser):
    """Vertrag mit optionaler Referenz – trennt mehrere Verträge beim selben Anbieter."""
    contract = service.add_contract(session, user, service.get_merchant(session, user, merchant_id), data.label,
                                    data.reference)
    session.commit()
    return contract


@router.delete("/contracts/{contract_id}", status_code=204)
def delete_contract(contract_id: int, session: SessionDep, user: CurrentUser):
    service.delete_contract(session, user, contract_id)
    session.commit()
    return Response(status_code=204)
