from sqlmodel import Session, func, select

from app.errors import Invalid
from app.models import Category, MappingRule, User
from app.schemas.rule import RuleCreate
from app.services.categorization import compile_pattern
from app.services.common import apply_changes, get_owned


def list_rules(session: Session, user: User) -> list[MappingRule]:
    return list(
        session.exec(
            select(MappingRule)
            .where(MappingRule.user_id == user.id)
            .order_by(MappingRule.priority, MappingRule.id)
        )
    )


def get_rule(session: Session, user: User, rule_id: int) -> MappingRule:
    return get_owned(session, MappingRule, rule_id, user.id, "Regel")


def _check_target(session: Session, user: User, category_id: int) -> None:
    category = get_owned(session, Category, category_id, user.id, "Kategorie")
    if not category.active:
        raise Invalid("Zielkategorie ist deaktiviert", code="category_inactive")


def create_rule(session: Session, user: User, data: RuleCreate) -> MappingRule:
    _check_target(session, user, data.target_category_id)
    compile_pattern(data.pattern, data.match_type, data.case_sensitive)
    rule = MappingRule(user_id=user.id, **data.model_dump())
    session.add(rule)
    session.flush()
    return rule


def update_rule(session: Session, user: User, rule: MappingRule, changes: dict) -> MappingRule:
    if changes.get("target_category_id") not in (None, rule.target_category_id):
        _check_target(session, user, changes["target_category_id"])
    compile_pattern(
        changes.get("pattern", rule.pattern),
        changes.get("match_type", rule.match_type),
        changes.get("case_sensitive", rule.case_sensitive),
    )
    apply_changes(rule, changes)
    session.flush()
    return rule


def delete_rule(session: Session, rule: MappingRule) -> None:
    """Bereits zugeordnete Kategorien bleiben; nur die Herkunftsangabe entfällt."""
    session.delete(rule)
    session.flush()


def rule_count_for_category(session: Session, category_id: int) -> int:
    return session.exec(select(func.count()).where(MappingRule.target_category_id == category_id)).one()
