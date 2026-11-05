from typing import Annotated, Any

from fastapi import APIRouter, Body

from app.deps import CurrentUser, SessionDep
from app.errors import Forbidden
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services import settings as settings_service
from app.services import users as service

router = APIRouter(prefix="/users", tags=["Profile"])


@router.get("", response_model=list[UserRead])
def list_users(session: SessionDep):
    """Alle Profile – für die Profilauswahl, daher ohne X-User-Id."""
    return service.list_users(session)


@router.post("", response_model=UserRead, status_code=201)
def create_user(data: UserCreate, session: SessionDep):
    """Profil anlegen; Standard- und Systemkategorien werden mit angelegt."""
    user = service.create_user(session, data.name)
    session.commit()
    return user


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, session: SessionDep):
    return service.get_user(session, user_id)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: int, data: UserUpdate, session: SessionDep):
    user = service.update_user(session, service.get_user(session, user_id), data.changes())
    session.commit()
    return user


def _own(user_id: int, user) -> None:
    if user.id != user_id:
        raise Forbidden("Einstellungen nur für das gewählte Profil", code="other_profile")


@router.get("/{user_id}/settings")
def get_settings(user_id: int, session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    """Einstellungen des Profils (Automatik, KI, Vorschau) mit Vorgaben."""
    _own(user_id, user)
    return settings_service.all_settings(session, user.id)


@router.patch("/{user_id}/settings")
def update_settings(
    user_id: int, session: SessionDep, user: CurrentUser, changes: Annotated[dict[str, Any], Body()]
) -> dict[str, Any]:
    _own(user_id, user)
    result = settings_service.update(session, user, changes)
    session.commit()
    return result
