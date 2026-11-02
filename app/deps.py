from typing import Annotated

from fastapi import Depends, Header
from sqlmodel import Session

from app.db import get_session
from app.errors import AppError, NotFound
from app.models import User

SessionDep = Annotated[Session, Depends(get_session)]


def get_current_user(
    session: SessionDep,
    x_user_id: Annotated[int | None, Header(description="ID des gewählten Profils")] = None,
) -> User:
    """Profilwahl ohne Passwort – bewusst kein Zugriffsschutz (nur internes Netz)."""
    if x_user_id is None:
        raise AppError("Header X-User-Id fehlt – bitte ein Profil wählen", code="profile_required")
    user = session.get(User, x_user_id)
    if user is None:
        raise NotFound(f"Profil {x_user_id} existiert nicht", code="profile_not_found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
