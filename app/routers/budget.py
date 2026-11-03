from datetime import UTC, date, datetime

from fastapi import APIRouter, Response

from app import clock
from app.deps import CurrentUser, SessionDep
from app.schemas.budget import BudgetMonth, FixedCostCreate, FixedCostRead, FixedCostUpdate, WallView
from app.services import budget as service

router = APIRouter()


@router.get("/fixed-costs", response_model=list[FixedCostRead], tags=["Fixkosten"])
def list_fixed_costs(session: SessionDep, user: CurrentUser):
    """Monatliche Fixkosten des Profils (Kreditraten kommen automatisch aus den Krediten dazu)."""
    return service.list_fixed_costs(session, user)


@router.post("/fixed-costs", response_model=FixedCostRead, status_code=201, tags=["Fixkosten"])
def create_fixed_cost(data: FixedCostCreate, session: SessionDep, user: CurrentUser):
    """`category_id` und/oder `match_text` erkennen die Zahlung im Monat („bezahlt“)."""
    fixed = service.create_fixed_cost(session, user, data)
    session.commit()
    return fixed


@router.get("/fixed-costs/{fixed_cost_id}", response_model=FixedCostRead, tags=["Fixkosten"])
def get_fixed_cost(fixed_cost_id: int, session: SessionDep, user: CurrentUser):
    return service.get_fixed_cost(session, user, fixed_cost_id)


@router.patch("/fixed-costs/{fixed_cost_id}", response_model=FixedCostRead, tags=["Fixkosten"])
def update_fixed_cost(fixed_cost_id: int, data: FixedCostUpdate, session: SessionDep, user: CurrentUser):
    fixed = service.update_fixed_cost(session, user, service.get_fixed_cost(session, user, fixed_cost_id),
                                      data.changes())
    session.commit()
    return fixed


@router.delete("/fixed-costs/{fixed_cost_id}", status_code=204, tags=["Fixkosten"])
def delete_fixed_cost(fixed_cost_id: int, session: SessionDep, user: CurrentUser):
    service.delete_fixed_cost(session, service.get_fixed_cost(session, user, fixed_cost_id))
    session.commit()
    return Response(status_code=204)


@router.get("/budget/month", response_model=BudgetMonth, tags=["Spielraum"])
def month_budget(session: SessionDep, user: CurrentUser, month: date | None = None):
    """Frei verfügbar im Monat (Standard: aktueller Monat) = Einnahmen − Fixkosten (inkl.
    Kreditraten) − variable Ausgaben, dazu jede Fixkost/Rate mit Status bezahlt/offen/überfällig."""
    today = clock.today()
    return service.month_budget(session, user.id, month or today, today)


@router.get("/wall", response_model=WallView, tags=["Wanddisplay"])
def wall(session: SessionDep):
    """Gemeinsamer Überblick fürs Wanddisplay: je Profil der Spielraum und offene Fälligkeiten,
    dazu alle Kredite mit Restschuld und Abbezahlt-Datum. Ohne Profilwahl, nur lesend, nur
    aus dem Heimnetz (globale Netzsperre, `ALLOWED_NETWORKS`)."""
    return service.wall_view(session, clock.today(), datetime.now(UTC))


