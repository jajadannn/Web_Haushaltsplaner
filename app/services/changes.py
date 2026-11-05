"""Änderungsverlauf für Übernahmen aus Vorschlägen – vorher/nachher und sichere Rücknahme.

Eine Rücknahme stellt den vorherigen Zustand nur wieder her, wenn das Objekt seit der Änderung
nicht manuell verändert wurde; sonst wird sie mit `changed_since` abgelehnt.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlmodel import Session, SQLModel, select

from app.errors import Conflict, NotFound
from app.models import ChangeActor, ChangeLog, User


def snapshot(obj: SQLModel, fields: tuple[str, ...]) -> dict[str, Any]:
    def plain(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, date):
            return value.isoformat()
        return value

    return {f: plain(getattr(obj, f)) for f in fields}


def record(
    session: Session,
    user_id: int,
    obj: SQLModel,
    fields: tuple[str, ...],
    *,
    action: str,
    before: dict[str, Any] | None,
    suggestion_id: int | None,
    actor: str = ChangeActor.USER,
) -> ChangeLog:
    entry = ChangeLog(
        user_id=user_id,
        object_type=obj.__tablename__,
        object_id=obj.id,
        action=action,
        before=before,
        after=snapshot(obj, fields),
        suggestion_id=suggestion_id,
        actor=actor,
    )
    session.add(entry)
    session.flush()
    return entry


def list_changes(session: Session, user: User, *, actor: str | None = None, limit: int = 100) -> list[ChangeLog]:
    query = select(ChangeLog).where(ChangeLog.user_id == user.id)
    if actor:
        query = query.where(ChangeLog.actor == actor)
    return list(session.exec(query.order_by(ChangeLog.created_at.desc(), ChangeLog.id.desc()).limit(limit)))


# Rücknahme je Objekttyp: (Modellklasse, Felder, Löschfunktion bei „create“)
REVERTERS: dict[str, tuple[type[SQLModel], tuple[str, ...], Callable[[Session, Any], None]]] = {}


def revert(session: Session, user: User, change_id: int) -> ChangeLog:
    change = session.get(ChangeLog, change_id, with_for_update=True)
    if change is None or change.user_id != user.id:
        raise NotFound(f"Änderung {change_id} nicht gefunden")
    if change.reverted_at is not None:
        raise Conflict("Änderung ist bereits zurückgenommen", code="already_reverted")
    model, fields, delete = REVERTERS[change.object_type]
    obj = session.get(model, change.object_id, with_for_update=True)
    # Verglichen werden die protokollierten Felder (ältere Einträge kennen neu aufgenommene Felder noch nicht)
    compared = tuple(f for f in fields if f in (change.after or {}))
    if obj is not None and snapshot(obj, compared) != change.after:
        raise Conflict("Seit der Änderung wurde manuell etwas geändert – bitte von Hand anpassen",
                       code="changed_since")
    if change.action == "create":
        if obj is not None:
            delete(session, obj)
    elif obj is not None and change.before is not None:
        for key, value in change.before.items():
            column = model.__table__.c[key]
            python_type = getattr(column.type, "python_type", None)
            if value is not None and python_type is Decimal:
                value = Decimal(value)
            elif value is not None and python_type is date:
                value = date.fromisoformat(value)
            setattr(obj, key, value)
    change.reverted_at = datetime.now(UTC)
    session.flush()
    return change
