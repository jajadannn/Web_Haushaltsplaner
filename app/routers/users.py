from fastapi import APIRouter

from app.deps import SessionDep
from app.schemas.user import UserCreate, UserRead, UserUpdate
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
