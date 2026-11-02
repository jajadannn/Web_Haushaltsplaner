from fastapi import APIRouter, Response

from app.deps import CurrentUser, SessionDep
from app.schemas.institution import InstitutionCreate, InstitutionRead, InstitutionUpdate
from app.services import institutions as service

router = APIRouter(prefix="/institutions", tags=["Banken"])


@router.get("", response_model=list[InstitutionRead])
def list_institutions(session: SessionDep, user: CurrentUser):
    return service.list_institutions(session, user)


@router.post("", response_model=InstitutionRead, status_code=201)
def create_institution(data: InstitutionCreate, session: SessionDep, user: CurrentUser):
    institution = service.create_institution(session, user, data)
    session.commit()
    return institution


@router.get("/{institution_id}", response_model=InstitutionRead)
def get_institution(institution_id: int, session: SessionDep, user: CurrentUser):
    return service.get_institution(session, user, institution_id)


@router.patch("/{institution_id}", response_model=InstitutionRead)
def update_institution(
    institution_id: int, data: InstitutionUpdate, session: SessionDep, user: CurrentUser
):
    institution = service.get_institution(session, user, institution_id)
    service.update_institution(session, institution, data.changes())
    session.commit()
    return institution


@router.delete("/{institution_id}", status_code=204)
def delete_institution(institution_id: int, session: SessionDep, user: CurrentUser):
    """Nur möglich, solange der Bank keine Konten zugeordnet sind (sonst 409)."""
    service.delete_institution(session, service.get_institution(session, user, institution_id))
    session.commit()
    return Response(status_code=204)
