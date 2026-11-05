from typing import Annotated, Any

from fastapi import APIRouter, Body, Query

from app.deps import CurrentUser, SessionDep
from app.schemas.suggestion import ChangeRead, RefreshResult, SuggestionRead
from app.services import analysis, changes
from app.services import suggestions as service

router = APIRouter(tags=["Vorschläge"])


@router.get("/suggestions", response_model=list[SuggestionRead])
def list_suggestions(
    session: SessionDep,
    user: CurrentUser,
    kind: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
):
    """Erkannte Vorschläge (Fixkosten, Regeln, Erstattungen …) mit Belegen und Begründung."""
    return service.list_suggestions(session, user, kind=kind, status=status)


@router.get("/suggestions/summary", response_model=dict[str, int])
def suggestion_summary(session: SessionDep, user: CurrentUser):
    """Anzahl offener Vorschläge je Art."""
    return service.summary(session, user)


@router.get("/suggestions/metrics")
def suggestion_metrics(session: SessionDep, user: CurrentUser, kind: str | None = None) -> dict[str, Any]:
    """Qualität der Vorschläge je Art und Erzeuger (Annahme-, Rücknahmequote)."""
    return service.metrics(session, user, kind)


@router.post("/suggestions/refresh", response_model=RefreshResult)
def refresh_suggestions(session: SessionDep, user: CurrentUser, detector: str | None = None):
    """Alle Erkennungen für das Profil sofort ausführen (sonst automatisch nach jedem Import)."""
    results = analysis.run_for(session, user, only=detector)
    session.commit()
    totals = {k: sum(r.get(k, 0) for r in results.values()) for k in ("new", "updated", "stale")}
    return {**totals, "by_detector": results}


@router.post("/suggestions/{suggestion_id}/accept", response_model=SuggestionRead)
def accept_suggestion(
    suggestion_id: int,
    session: SessionDep,
    user: CurrentUser,
    overrides: Annotated[dict[str, Any] | None, Body()] = None,
):
    """Übernehmen, optional mit geänderten Werten (z. B. Name oder Betrag)."""
    suggestion = service.accept(session, user, suggestion_id, overrides or {})
    session.commit()
    return suggestion


@router.post("/suggestions/{suggestion_id}/reject", response_model=SuggestionRead)
def reject_suggestion(suggestion_id: int, session: SessionDep, user: CurrentUser):
    """Ablehnen – derselbe Fall wird nicht erneut vorgeschlagen, solange nichts Wesentliches neu ist."""
    suggestion = service.reject(session, user, suggestion_id)
    session.commit()
    return suggestion


@router.post("/suggestions/{suggestion_id}/revert", response_model=SuggestionRead)
def revert_suggestion(suggestion_id: int, session: SessionDep, user: CurrentUser):
    """Übernahme zurücknehmen – nur wenn seitdem nichts manuell geändert wurde."""
    suggestion = service.revert(session, user, suggestion_id)
    session.commit()
    return suggestion


@router.get("/changes", response_model=list[ChangeRead], tags=["Verlauf"])
def list_changes(session: SessionDep, user: CurrentUser, actor: str | None = None,
                 limit: Annotated[int, Query(ge=1, le=500)] = 100):
    """Änderungsverlauf aus übernommenen und automatisch angewendeten Vorschlägen."""
    return changes.list_changes(session, user, actor=actor, limit=limit)


@router.post("/changes/{change_id}/revert", response_model=ChangeRead, tags=["Verlauf"])
def revert_change(change_id: int, session: SessionDep, user: CurrentUser):
    change = changes.revert(session, user, change_id)
    session.commit()
    return change
