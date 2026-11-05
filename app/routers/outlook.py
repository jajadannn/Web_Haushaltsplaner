from datetime import date

from fastapi import APIRouter, Response

from app.deps import CurrentUser, SessionDep
from app.schemas.outlook import ExpectedIncomeCreate, ExpectedIncomeRead, ExpectedIncomeUpdate, Forecast
from app.services import outlook as service

router = APIRouter()


@router.get("/expected-incomes", response_model=list[ExpectedIncomeRead], tags=["Vorschau"])
def list_incomes(session: SessionDep, user: CurrentUser):
    """Erwartete regelmäßige Einnahmen – nur für Vorschau und Hinweise, nie als Buchung."""
    return service.list_incomes(session, user)


@router.post("/expected-incomes", response_model=ExpectedIncomeRead, status_code=201, tags=["Vorschau"])
def create_income(data: ExpectedIncomeCreate, session: SessionDep, user: CurrentUser):
    income = service.create_income(session, user, data.model_dump())
    session.commit()
    return income


@router.patch("/expected-incomes/{income_id}", response_model=ExpectedIncomeRead, tags=["Vorschau"])
def update_income(income_id: int, data: ExpectedIncomeUpdate, session: SessionDep, user: CurrentUser):
    income = service.update_income(session, user, service.get_income(session, user, income_id), data.changes())
    session.commit()
    return income


@router.delete("/expected-incomes/{income_id}", status_code=204, tags=["Vorschau"])
def delete_income(income_id: int, session: SessionDep, user: CurrentUser):
    service.delete_income(session, service.get_income(session, user, income_id))
    session.commit()
    return Response(status_code=204)


@router.get("/accounts/{account_id}/forecast", response_model=Forecast, tags=["Vorschau"])
def account_forecast(account_id: int, until: date, session: SessionDep, user: CurrentUser):
    """Kontostand heute und erwartete Fixkosten, Raten und Einnahmen bis `until` – getrennt gekennzeichnet."""
    return service.forecast(session, user, account_id, until)
