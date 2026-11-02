from sqlmodel import Session, func, select

from app.errors import Conflict
from app.models import Account, Institution, User
from app.schemas.institution import InstitutionCreate
from app.services.common import apply_changes, flush_or_conflict, get_owned

_UNIQUE = {"uq_institution_user_id_name": "Eine Bank mit diesem Namen existiert bereits"}


def list_institutions(session: Session, user: User) -> list[Institution]:
    query = select(Institution).where(Institution.user_id == user.id)
    return list(session.exec(query.order_by(func.lower(Institution.name), Institution.id)))


def get_institution(session: Session, user: User, institution_id: int) -> Institution:
    return get_owned(session, Institution, institution_id, user.id, "Bank")


def create_institution(session: Session, user: User, data: InstitutionCreate) -> Institution:
    institution = Institution(user_id=user.id, **data.model_dump())
    session.add(institution)
    flush_or_conflict(session, _UNIQUE)
    return institution


def update_institution(session: Session, institution: Institution, changes: dict) -> Institution:
    apply_changes(institution, changes)
    flush_or_conflict(session, _UNIQUE)
    return institution


def delete_institution(session: Session, institution: Institution) -> None:
    accounts = session.exec(
        select(func.count()).where(Account.institution_id == institution.id)
    ).one()
    if accounts:
        raise Conflict(
            "Bank hat noch Konten – erst Konten löschen oder einer anderen Bank zuordnen",
            code="institution_in_use",
            details={"accounts": accounts},
        )
    session.delete(institution)
    session.flush()
