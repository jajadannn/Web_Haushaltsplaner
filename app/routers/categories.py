from fastapi import APIRouter, Response

from app.deps import CurrentUser, SessionDep
from app.models import CategoryType
from app.schemas.category import CategoryCreate, CategoryMerge, CategoryRead, CategoryUpdate
from app.services import categories as service

router = APIRouter(prefix="/categories", tags=["Kategorien"])


@router.get("", response_model=list[CategoryRead])
def list_categories(
    session: SessionDep,
    user: CurrentUser,
    type: CategoryType | None = None,
    active: bool | None = None,
):
    """Flache Liste; der Baum ergibt sich über `parent_id`."""
    return service.list_categories(session, user, cat_type=type, active=active)


@router.post("", response_model=CategoryRead, status_code=201)
def create_category(data: CategoryCreate, session: SessionDep, user: CurrentUser):
    category = service.create_category(session, user, data)
    session.commit()
    return category


@router.get("/{category_id}", response_model=CategoryRead)
def get_category(category_id: int, session: SessionDep, user: CurrentUser):
    return service.get_category(session, user, category_id)


@router.patch("/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: int, data: CategoryUpdate, session: SessionDep, user: CurrentUser
):
    """Auch zum Deaktivieren (`active: false`) verwendeter Kategorien."""
    category = service.get_category(session, user, category_id)
    service.update_category(session, user, category, data.changes())
    session.commit()
    return category


@router.post("/{category_id}/merge", response_model=CategoryRead)
def merge_category(
    category_id: int, data: CategoryMerge, session: SessionDep, user: CurrentUser
):
    """Führt diese Kategorie in `target_id` zusammen und löscht sie anschließend."""
    source = service.get_category(session, user, category_id)
    target = service.merge_category(session, user, source, data.target_id)
    session.commit()
    return target


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: int, session: SessionDep, user: CurrentUser):
    """Nur unbenutzte Kategorien; sonst 409 – dann deaktivieren oder zusammenführen."""
    service.delete_category(session, service.get_category(session, user, category_id))
    session.commit()
    return Response(status_code=204)
