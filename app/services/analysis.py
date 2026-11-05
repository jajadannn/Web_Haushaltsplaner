"""Auswertungen nach einem Import (B5): erkennt Fixkosten, Erstattungen, fehlende Zahlungen …

`mark_due` wird beim Abschluss eines Imports aufgerufen und merkt das Profil nur vor – die
eigentliche Arbeit macht der Worker (`run_due`) außerhalb der Importtransaktion, höchstens ein
Profil je Durchlauf. Ein Fehler in einer Analyse blockiert nie den Import oder die anderen Analysen.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

from sqlalchemy import or_
from sqlmodel import Session, select

from app import clock
from app.models import AnalysisState, User

log = logging.getLogger("finanzplaner.analysis")

# Name → Funktion(session, user, today) -> {"new", "updated", "stale"}; Reihenfolge = Ausführung
DETECTORS: dict[str, Callable[[Session, User, date], dict[str, int]]] = {}


def register(name: str, detector: Callable[[Session, User, date], dict[str, int]]) -> None:
    DETECTORS[name] = detector


def mark_due(session: Session, user_id: int) -> None:
    state = session.get(AnalysisState, user_id)
    if state is None:
        session.add(AnalysisState(user_id=user_id, due_at=datetime.now(UTC)))
    else:
        state.due_at = datetime.now(UTC)
    session.flush()


def run_for(session: Session, user: User, today: date | None = None, only: str | None = None) -> dict[str, dict]:
    """Alle (oder eine) Analysen für ein Profil; jede in eigenem Savepoint."""
    today = today or clock.today()
    results = {}
    for name, detector in DETECTORS.items():
        if only and name != only:
            continue
        savepoint = session.begin_nested()
        try:
            results[name] = detector(session, user, today)
            savepoint.commit()
        except Exception:
            savepoint.rollback()
            log.exception("Analyse %s für Profil %s fehlgeschlagen", name, user.id)
            results[name] = {"error": 1}
    state = session.get(AnalysisState, user.id)
    if state is None:
        session.add(AnalysisState(user_id=user.id, last_run_at=datetime.now(UTC)))
    else:
        state.due_at, state.last_run_at = None, datetime.now(UTC)
    session.flush()
    return results


def run_due(session: Session) -> int | None:
    """Ein vorgemerktes Profil auswerten (Worker); gibt die Profil-ID zurück oder None."""
    state = session.exec(
        select(AnalysisState)
        .where(AnalysisState.due_at.is_not(None),
               or_(AnalysisState.last_run_at.is_(None), AnalysisState.last_run_at < AnalysisState.due_at))
        .order_by(AnalysisState.due_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if state is None:
        return None
    user = session.get(User, state.user_id)
    run_for(session, user)
    session.commit()
    return user.id


def _load_detectors() -> None:
    from app.services import recurring

    register("fixed_costs", recurring.refresh)
    from app.services import clarify, upkeep  # noqa: F401 – registrieren ihre Erkennungen


_load_detectors()
