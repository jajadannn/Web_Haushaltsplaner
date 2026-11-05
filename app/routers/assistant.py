from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.deps import CurrentUser, SessionDep
from app.services import assistant as service

router = APIRouter(tags=["Assistent"])


class AskIn(BaseModel):
    question: Annotated[str, Field(min_length=3, max_length=500)]


class ParseIn(BaseModel):
    text: Annotated[str, Field(min_length=2, max_length=300)]


@router.get("/reports/month-comparison", tags=["Berichte"])
def month_comparison(month: date, session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    """Monat gegen Vormonat und Schnitt der drei Monate davor: Hauptkategorien, größte Buchungen, Einmaleffekte."""
    return service.reports_jsonable(service.month_comparison(session, user, month))


@router.post("/reports/month-comparison/explain", tags=["Berichte"])
def explain_month(month: date, session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    """Kurze Erklärung der Veränderung durch die lokale KI – nur aus den berechneten Zahlen."""
    result = service.explain_month(session, user, month)
    session.commit()  # Zwischenspeicher der KI-Antwort
    return service.reports_jsonable(result)


@router.post("/ask")
def ask(data: AskIn, session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    """Frage zu den eigenen Buchungen – nur lesend, über eine feste Liste von Auswertungen."""
    return service.reports_jsonable(service.ask(session, user, data.question))


@router.post("/entries/parse")
def parse_entry(data: ParseIn, session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    """Buchungsentwurf aus einer Beschreibung („Gestern 18,50 € bar Mittagessen“) – speichert nichts."""
    return service.reports_jsonable(service.parse_entry(session, user, data.text))
