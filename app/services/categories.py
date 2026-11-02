from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, func, select

from app.errors import Conflict, Invalid
from app.models import Category, MappingRule, Transaction, TransactionSplit, User
from app.schemas.category import CategoryCreate
from app.services.category_defaults import DEFAULT_CATEGORIES, DefaultCategory
from app.services.common import apply_changes, flush_or_conflict, get_owned

_UNIQUE = {
    "uq_category_user_id_parent_id_name": (
        "Eine Kategorie mit diesem Namen existiert auf dieser Ebene bereits"
    ),
}


# --- Standardkategorien -------------------------------------------------------


def _insert_default(
    session: Session, user_id: int, default: DefaultCategory, parent_id: int | None
) -> int:
    stmt = (
        insert(Category)
        .values(
            user_id=user_id,
            name=default.name,
            type=default.type,
            icon=default.icon,
            color=default.color,
            parent_id=parent_id,
            active=True,
            system_key=default.system_key,
        )
        .on_conflict_do_nothing()
        .returning(Category.id)
    )
    new_id = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        return new_id
    # Existiert bereits (z. B. wiederholter Seed) – vorhandene ID verwenden
    query = select(Category.id).where(Category.user_id == user_id)
    if default.system_key:
        query = query.where(Category.system_key == default.system_key)
    else:
        query = query.where(
            Category.name == default.name, Category.parent_id.is_not_distinct_from(parent_id)
        )
    return session.exec(query).one()


def seed_default_categories(session: Session, user_id: int) -> None:
    """Legt die Standard- und Systemkategorien an; mehrfacher Aufruf erzeugt keine Dubletten."""
    for top in DEFAULT_CATEGORIES:
        parent_id = _insert_default(session, user_id, top, None)
        for child in top.children:
            _insert_default(session, user_id, child, parent_id)
    session.flush()


# --- Hilfen -------------------------------------------------------------------


def _ancestor_ids(session: Session, category: Category) -> list[int]:
    ids: list[int] = []
    current = category
    while current.parent_id is not None and current.parent_id not in ids:
        ids.append(current.parent_id)
        current = session.get(Category, current.parent_id)
    return ids


def _child_count(session: Session, category_id: int) -> int:
    return session.exec(select(func.count()).where(Category.parent_id == category_id)).one()


def _usage(session: Session, category: Category) -> dict[str, int]:
    """Verwendungen, die Löschen und Typwechsel verhindern."""
    usage = {
        "children": _child_count(session, category.id),
        "transactions": session.exec(
            select(func.count()).where(Transaction.category_id == category.id)
        ).one(),
        "splits": session.exec(
            select(func.count()).where(TransactionSplit.category_id == category.id)
        ).one(),
        "rules": session.exec(
            select(func.count()).where(MappingRule.target_category_id == category.id)
        ).one(),
    }
    return {k: v for k, v in usage.items() if v}


def _validate_parent(
    session: Session, user: User, category: Category | None, parent_id: int, cat_type: str
) -> Category:
    parent = get_owned(session, Category, parent_id, user.id, "Elternkategorie")
    if parent.type != cat_type:
        raise Invalid(
            "Elternkategorie muss denselben Typ (Einnahme/Ausgabe) haben",
            code="parent_type_mismatch",
        )
    if category is not None and (
        parent.id == category.id or category.id in _ancestor_ids(session, parent)
    ):
        raise Invalid(
            "Kategorie kann nicht unter sich selbst oder eine eigene Unterkategorie gehängt werden",
            code="category_cycle",
        )
    return parent


# --- CRUD ---------------------------------------------------------------------


def list_categories(
    session: Session, user: User, *, cat_type: str | None = None, active: bool | None = None
) -> list[Category]:
    query = select(Category).where(Category.user_id == user.id)
    if cat_type is not None:
        query = query.where(Category.type == cat_type)
    if active is not None:
        query = query.where(Category.active == active)
    return list(session.exec(query.order_by(func.lower(Category.name), Category.id)))


def get_category(session: Session, user: User, category_id: int) -> Category:
    return get_owned(session, Category, category_id, user.id, "Kategorie")


def get_system_category(session: Session, user_id: int, system_key: str) -> Category:
    """Liefert eine Systemkategorie (z. B. loan_interest) und legt sie bei Bedarf an."""
    query = select(Category).where(
        Category.user_id == user_id, Category.system_key == system_key
    )
    category = session.exec(query).first()
    if category is None:
        seed_default_categories(session, user_id)
        category = session.exec(query).one()
    return category


def create_category(session: Session, user: User, data: CategoryCreate) -> Category:
    if data.parent_id is not None:
        _validate_parent(session, user, None, data.parent_id, data.type)
    category = Category(user_id=user.id, **data.model_dump())
    session.add(category)
    flush_or_conflict(session, _UNIQUE)
    return category


def update_category(session: Session, user: User, category: Category, changes: dict) -> Category:
    new_type = changes.get("type", category.type)
    if new_type != category.type:
        if category.system_key:
            raise Invalid("Typ einer Systemkategorie ist fest", code="system_category")
        if _usage(session, category):
            raise Conflict(
                "Typ kann nur bei unbenutzten Kategorien ohne Unterkategorien geändert werden",
                code="category_in_use",
                details=_usage(session, category),
            )
    if changes.get("active") is False and category.system_key:
        raise Invalid("Systemkategorien können nicht deaktiviert werden", code="system_category")

    parent_id = changes.get("parent_id", category.parent_id)
    if parent_id is not None and ("parent_id" in changes or "type" in changes):
        _validate_parent(session, user, category, parent_id, new_type)

    apply_changes(category, changes)
    flush_or_conflict(session, _UNIQUE)
    return category


def delete_category(session: Session, category: Category) -> None:
    if category.system_key:
        raise Conflict("Systemkategorien können nicht gelöscht werden", code="system_category")
    usage = _usage(session, category)
    if usage:
        raise Conflict(
            "Kategorie wird noch verwendet – deaktivieren oder zusammenführen",
            code="category_in_use",
            details=usage,
        )
    session.delete(category)
    session.flush()


def merge_category(session: Session, user: User, source: Category, target_id: int) -> Category:
    """Hängt alles von `source` an `target` um und löscht `source`."""
    target = get_owned(session, Category, target_id, user.id, "Zielkategorie")
    if target.id == source.id:
        raise Invalid("Quelle und Ziel sind identisch", code="merge_same_category")
    if source.system_key:
        raise Conflict("Systemkategorien können nicht zusammengeführt werden", code="system_category")
    if target.type != source.type:
        raise Invalid("Nur Kategorien desselben Typs können zusammengeführt werden",
                      code="parent_type_mismatch")
    if not target.active:
        raise Invalid("Zielkategorie ist deaktiviert", code="category_inactive")
    if source.id in _ancestor_ids(session, target):
        raise Invalid("Ziel darf keine Unterkategorie der Quelle sein", code="category_cycle")

    children = list(session.exec(select(Category).where(Category.parent_id == source.id)))
    target_child_names = set(
        session.exec(select(Category.name).where(Category.parent_id == target.id))
    )
    clashes = sorted(c.name for c in children if c.name in target_child_names)
    if clashes:
        raise Conflict(
            "Gleichnamige Unterkategorien zuerst zusammenführen",
            code="merge_name_clash",
            details={"names": clashes},
        )
    for child in children:
        child.parent_id = target.id
    for model in (Transaction, TransactionSplit):
        session.execute(
            update(model).where(model.category_id == source.id).values(category_id=target.id)
        )
    session.execute(
        update(MappingRule)
        .where(MappingRule.target_category_id == source.id)
        .values(target_category_id=target.id)
    )
    session.flush()
    session.expire_all()
    session.delete(source)
    session.flush()
    return target
