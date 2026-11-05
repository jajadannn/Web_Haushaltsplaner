from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

from app.errors import Conflict, NotFound


def get_owned[T: SQLModel](session: Session, model: type[T], obj_id: int, user_id: int, label: str) -> T:
    """Lädt eine Ressource des Profils; fremde Ressourcen sind wie nicht existent (404)."""
    obj = session.get(model, obj_id)
    if obj is None or obj.user_id != user_id:
        raise NotFound(f"{label} {obj_id} nicht gefunden")
    return obj


def flush_or_conflict(session: Session, messages: dict[str, str]) -> None:
    """Flush; bekannte Unique-Verletzungen werden zu verständlichen 409-Fehlern."""
    try:
        session.flush()
    except IntegrityError as exc:
        # In einem Savepoint (z. B. Automatik) rollt der Aufrufer genau diesen zurück; sonst die Transaktion.
        if not session.in_nested_transaction():
            session.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint in messages:
            raise Conflict(messages[constraint], details={"constraint": constraint}) from exc
        raise


def apply_changes(obj: SQLModel, changes: dict) -> None:
    for key, value in changes.items():
        setattr(obj, key, value)
