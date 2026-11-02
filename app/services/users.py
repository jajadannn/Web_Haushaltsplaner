from sqlmodel import Session, func, select

from app.errors import NotFound
from app.models import User
from app.services.categories import seed_default_categories
from app.services.common import apply_changes, flush_or_conflict

_UNIQUE = {"uq_app_user_name": "Ein Profil mit diesem Namen existiert bereits"}


def list_users(session: Session) -> list[User]:
    return list(session.exec(select(User).order_by(func.lower(User.name), User.id)))


def get_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise NotFound(f"Profil {user_id} nicht gefunden", code="profile_not_found")
    return user


def create_user(session: Session, name: str) -> User:
    user = User(name=name)
    session.add(user)
    flush_or_conflict(session, _UNIQUE)
    seed_default_categories(session, user.id)
    return user


def update_user(session: Session, user: User, changes: dict) -> User:
    apply_changes(user, changes)
    flush_or_conflict(session, _UNIQUE)
    return user
