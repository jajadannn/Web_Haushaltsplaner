from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse

from app import clock
from app.deps import CurrentUser, SessionDep
from app.errors import Invalid
from app.schemas.filters import TransactionFilter
from app.schemas.report import CategoryReport, LoanReport, SummaryReport, TrendReport
from app.services import export, reports
from app.services.loans.core import get_loan

router = APIRouter()


def _period(date_from: date, date_to: date) -> None:
    if date_from > date_to:
        raise Invalid("date_from liegt nach date_to", code="invalid_period")


@router.get("/reports/summary", response_model=SummaryReport, tags=["Berichte"])
def summary(session: SessionDep, user: CurrentUser, date_from: date, date_to: date):
    """Salden je Konto/Bank am Ende von `date_to`, Nettovermögen (Vermögen + Verbindlichkeiten)
    sowie Einnahmen/Ausgaben im Zeitraum (inkl. Monatswerten). Umbuchungen und Tilgungen
    zählen nicht als Ausgabe; Kreditzinsen schon."""
    _period(date_from, date_to)
    return reports.summary(session, user, date_from, date_to)


@router.get("/reports/categories", response_model=CategoryReport, tags=["Berichte"])
def categories(
    session: SessionDep,
    user: CurrentUser,
    date_from: date,
    date_to: date,
    type: Literal["income", "expense"] = "expense",
):
    """Brutto, Erstattungen und Netto je Kategorie; Elternkategorien enthalten ihre
    Unterkategorien. `share` fehlt bei Netto ≤ 0 (kein sinnvoller Tortenanteil)."""
    _period(date_from, date_to)
    return reports.categories(session, user, date_from, date_to, type)


@router.get("/reports/trends", response_model=TrendReport, tags=["Berichte"])
def trends(
    session: SessionDep,
    user: CurrentUser,
    months: Annotated[int, Query(ge=1, le=120)] = 12,
    until: date | None = None,
    category_id: int | None = None,
):
    """Monatswerte der letzten `months` Monate, lückenlos. `coverage: unknown` – ein Monat
    ohne Buchungen heißt nicht sicher, dass es keine Umsätze gab (evtl. fehlt ein Import)."""
    if category_id is not None:
        from app.services.categories import get_category

        get_category(session, user, category_id)
    return reports.trends(session, user, months, until or clock.today(), category_id)


@router.get("/reports/loans", response_model=LoanReport, tags=["Berichte"])
def loans(
    session: SessionDep,
    user: CurrentUser,
    months: Annotated[int, Query(ge=1, le=120)] = 12,
    until: date | None = None,
):
    """Restschuld je Kredit zum Monatsende, gezahlte Zinsen je Jahr, monatliche Ratenbelastung."""
    return reports.loans(session, user, until or clock.today(), months)


@router.get("/export/transactions.csv", tags=["Export"])
def export_transactions(session: SessionDep, user: CurrentUser, filters: Annotated[TransactionFilter, Query()]):
    """Alle gefilterten Buchungen als CSV (Semikolon, UTF-8, Dezimalkomma); Splits als eigene Zeilen."""
    return StreamingResponse(
        export.transactions_csv(session, user, filters),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="buchungen.csv"'},
    )


@router.get("/export/report.pdf", tags=["Export"])
def export_report(session: SessionDep, user: CurrentUser, date_from: date, date_to: date):
    _period(date_from, date_to)
    return Response(
        export.report_pdf(session, user, date_from, date_to),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="finanzbericht.pdf"'},
    )


@router.get("/export/loans/{loan_id}/schedule.csv", tags=["Export"])
def export_schedule_csv(loan_id: int, session: SessionDep, user: CurrentUser):
    loan = get_loan(session, user, loan_id)
    return StreamingResponse(
        export.schedule_csv(session, loan),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="tilgungsplan-{loan_id}.csv"'},
    )


@router.get("/export/loans/{loan_id}/schedule.pdf", tags=["Export"])
def export_schedule_pdf(loan_id: int, session: SessionDep, user: CurrentUser):
    loan = get_loan(session, user, loan_id)
    return Response(
        export.schedule_pdf(session, loan),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="tilgungsplan-{loan_id}.pdf"'},
    )
