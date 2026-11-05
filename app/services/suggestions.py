"""Vorschlagsspeicher: erkannte Fälle mit Belegen speichern, übernehmen, ablehnen, zurücknehmen.

Jede Vorschlagsart (`kind`) hat einen Handler mit
- `validate`: prüft unter Sperre, ob der Vorschlag noch zum aktuellen Datenstand passt,
- `apply`: setzt ihn über die vorhandenen Fach-Services um und liefert (result_type, result_id),
- optional `is_clear`: eindeutiger Fall, den die Automatik ohne Rückfrage übernehmen darf.

Erkennungsdienste melden ihre Funde über `sync()`. Abgelehnte Vorschläge bleiben abgelehnt,
außer `reopen` meldet wesentlich neue Evidenz; Vorschläge, die nicht mehr erkannt werden oder
deren Belege fehlen, werden `stale`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlmodel import Session, func, select

from app.errors import Conflict, NotFound
from app.models import ChangeActor, ChangeLog, Suggestion, SuggestionStatus, User
from app.services import changes, settings
from app.services.common import get_owned

ACCEPTABLE = (SuggestionStatus.OPEN, SuggestionStatus.DRY_RUN)


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return value


@dataclass
class Found:
    """Ein erkannter Fall, wie ihn ein Erkennungsdienst liefert."""

    fingerprint: str
    payload: dict[str, Any]
    evidence: dict[str, Any]
    reason: str
    priority: int = 0


@dataclass
class Handler:
    validate: Callable[[Session, User, Suggestion], None]
    apply: Callable[[Session, User, Suggestion, dict[str, Any], str], tuple[str, int | None]]
    is_clear: Callable[[Suggestion], bool] = lambda s: False
    setting: str | None = None  # Einstellung für die Automatik, z. B. "automation.fixed_cost"
    reopen: Callable[[dict, dict], str | None] = lambda old, new: None
    evidence_valid: Callable[[Session, Suggestion], bool] = lambda session, s: True
    extra: dict[str, Any] = field(default_factory=dict)


HANDLERS: dict[str, Handler] = {}


def register(kind: str, handler: Handler) -> None:
    HANDLERS[kind] = handler


# --- Erkennungsergebnisse übernehmen -------------------------------------------------------------


def sync(session: Session, user: User, kind: str, found: list[Found], generator: str) -> dict[str, int]:
    """Gleicht die aktuellen Funde einer Art mit dem Speicher ab."""
    handler = HANDLERS[kind]
    existing = {
        s.fingerprint: s
        for s in session.exec(select(Suggestion).where(Suggestion.user_id == user.id, Suggestion.kind == kind))
    }
    now = datetime.now(UTC)
    counts = {"new": 0, "updated": 0, "stale": 0}
    seen = set()
    for item in found:
        seen.add(item.fingerprint)
        payload, evidence = jsonable(item.payload), jsonable(item.evidence)
        old = existing.get(item.fingerprint)
        if old is None:
            session.add(Suggestion(
                user_id=user.id, kind=kind, fingerprint=item.fingerprint, payload=payload, evidence=evidence,
                reason=item.reason, generator=generator, priority=item.priority, data_as_of=now,
            ))
            counts["new"] += 1
            continue
        if old.status in (SuggestionStatus.OPEN, SuggestionStatus.DRY_RUN, SuggestionStatus.STALE):
            if old.payload != payload or old.evidence != evidence or old.status == SuggestionStatus.STALE:
                counts["updated"] += 1
            old.payload, old.evidence, old.reason = payload, evidence, item.reason
            old.generator, old.priority, old.data_as_of = generator, item.priority, now
            if old.status == SuggestionStatus.STALE:
                old.status = SuggestionStatus.OPEN
        elif old.status == SuggestionStatus.REJECTED:
            why = handler.reopen(old.payload, payload)
            if why:
                old.payload, old.evidence, old.data_as_of = payload, evidence, now
                old.reason = f"Neu bewertet: {why}. {item.reason}"
                old.status, old.decided_at = SuggestionStatus.OPEN, None
                counts["updated"] += 1
    for fingerprint, old in existing.items():
        if fingerprint not in seen and old.status in (SuggestionStatus.OPEN, SuggestionStatus.DRY_RUN):
            old.status = SuggestionStatus.STALE
            counts["stale"] += 1
    session.flush()
    _automate(session, user, kind)
    return counts


def _automate(session: Session, user: User, kind: str) -> None:
    handler = HANDLERS[kind]
    if handler.setting is None:
        return
    mode = settings.get(session, user.id, handler.setting)
    if mode not in ("dry_run", "auto"):
        return
    for suggestion in session.exec(
        select(Suggestion).where(
            Suggestion.user_id == user.id, Suggestion.kind == kind, Suggestion.status == SuggestionStatus.OPEN
        )
    ).all():
        if not handler.is_clear(suggestion):
            continue
        if mode == "dry_run":
            suggestion.status = SuggestionStatus.DRY_RUN
            continue
        savepoint = session.begin_nested()
        try:
            _apply(session, user, suggestion, {}, ChangeActor.AUTO)
            suggestion.status = SuggestionStatus.AUTO_APPLIED
            savepoint.commit()
        except Conflict:
            savepoint.rollback()
    session.flush()


# --- Lesen ---------------------------------------------------------------------------------------


def list_suggestions(
    session: Session, user: User, *, kind: str | None = None, status: str | None = None
) -> list[Suggestion]:
    query = select(Suggestion).where(Suggestion.user_id == user.id)
    if kind:
        query = query.where(Suggestion.kind == kind)
    if status:
        query = query.where(Suggestion.status == status)
    return list(session.exec(query.order_by(Suggestion.priority.desc(), Suggestion.created_at, Suggestion.id)))


def summary(session: Session, user: User) -> dict[str, int]:
    rows = session.exec(
        select(Suggestion.kind, func.count())
        .where(Suggestion.user_id == user.id, Suggestion.status.in_(ACCEPTABLE))
        .group_by(Suggestion.kind)
    )
    return dict(rows.all())


def get_suggestion(session: Session, user: User, suggestion_id: int) -> Suggestion:
    return get_owned(session, Suggestion, suggestion_id, user.id, "Vorschlag")


# --- Entscheiden ---------------------------------------------------------------------------------


def _lock(session: Session, user: User, suggestion_id: int) -> Suggestion:
    suggestion = session.get(Suggestion, suggestion_id, with_for_update=True, populate_existing=True)
    if suggestion is None or suggestion.user_id != user.id:
        raise NotFound(f"Vorschlag {suggestion_id} nicht gefunden")
    return suggestion


def _apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str) -> None:
    handler = HANDLERS[suggestion.kind]
    if not handler.evidence_valid(session, suggestion):
        suggestion.status = SuggestionStatus.STALE
        raise Conflict("Die Belege dieses Vorschlags haben sich geändert", code="suggestion_stale")
    handler.validate(session, user, suggestion)
    result_type, result_id = handler.apply(session, user, suggestion, overrides, actor)
    suggestion.result_type, suggestion.result_id = result_type, result_id
    suggestion.decided_at = datetime.now(UTC)


def accept(session: Session, user: User, suggestion_id: int, overrides: dict | None = None) -> Suggestion:
    suggestion = _lock(session, user, suggestion_id)
    if suggestion.status not in ACCEPTABLE:
        raise Conflict("Vorschlag ist nicht mehr offen", code="suggestion_not_open",
                       details={"status": suggestion.status})
    _apply(session, user, suggestion, overrides or {}, ChangeActor.USER)
    suggestion.status = SuggestionStatus.ACCEPTED
    session.flush()
    return suggestion


def reject(session: Session, user: User, suggestion_id: int) -> Suggestion:
    suggestion = _lock(session, user, suggestion_id)
    if suggestion.status not in (*ACCEPTABLE, SuggestionStatus.STALE):
        raise Conflict("Vorschlag ist nicht mehr offen", code="suggestion_not_open",
                       details={"status": suggestion.status})
    suggestion.status, suggestion.decided_at = SuggestionStatus.REJECTED, datetime.now(UTC)
    session.flush()
    return suggestion


def revert(session: Session, user: User, suggestion_id: int) -> Suggestion:
    """Nimmt eine übernommene Änderung zurück (über den Änderungsverlauf)."""
    suggestion = _lock(session, user, suggestion_id)
    if suggestion.status not in (SuggestionStatus.ACCEPTED, SuggestionStatus.AUTO_APPLIED):
        raise Conflict("Nur übernommene Vorschläge lassen sich zurücknehmen", code="suggestion_not_applied")
    entries = session.exec(
        select(ChangeLog).where(ChangeLog.suggestion_id == suggestion.id, ChangeLog.reverted_at.is_(None))
        .order_by(ChangeLog.id.desc())
    ).all()
    for entry in entries:
        changes.revert(session, user, entry.id)
    suggestion.status = SuggestionStatus.REVERTED
    session.flush()
    return suggestion


def metrics(session: Session, user: User, kind: str | None = None) -> dict[str, Any]:
    """Qualität der Vorschläge: Anteile je Ausgang, getrennt nach Erzeuger (Regel-/Modellversion)."""
    query = select(Suggestion.kind, Suggestion.generator, Suggestion.status, func.count()).where(
        Suggestion.user_id == user.id
    )
    if kind:
        query = query.where(Suggestion.kind == kind)
    rows = session.exec(query.group_by(Suggestion.kind, Suggestion.generator, Suggestion.status)).all()
    result: dict[tuple[str, str], dict[str, int]] = {}
    for k, generator, status, count in rows:
        result.setdefault((k, generator), {})[status] = count
    corrected = dict(
        session.exec(
            select(ChangeLog.suggestion_id, func.count())
            .where(ChangeLog.user_id == user.id, ChangeLog.suggestion_id.is_not(None),
                   ChangeLog.reverted_at.is_not(None))
            .group_by(ChangeLog.suggestion_id)
        ).all()
    )
    out = []
    for (k, generator), counts in sorted(result.items()):
        decided = sum(counts.get(s, 0) for s in ("accepted", "rejected", "auto_applied", "reverted"))
        accepted = counts.get("accepted", 0) + counts.get("auto_applied", 0)
        out.append({
            "kind": k,
            "generator": generator,
            "counts": counts,
            "acceptance_rate": round(accepted / decided, 3) if decided else None,
            "revert_rate": round(counts.get("reverted", 0) / accepted, 3) if accepted else None,
        })
    return {"items": out, "reverted_changes": sum(corrected.values())}
