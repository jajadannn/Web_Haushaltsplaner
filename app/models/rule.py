from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKeyConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import created_at_column, enum_check, enum_column, updated_at_column


class MatchType(StrEnum):
    CONTAINS = "contains"  # Teiltext (Standard)
    REGEX = "regex"  # regulärer Ausdruck, mit Zeitlimit ausgewertet


class MatchField(StrEnum):
    DESCRIPTION = "description"
    COUNTERPARTY = "counterparty"
    ANY = "any"  # Verwendungszweck oder Gegenpartei


class MappingRule(SQLModel, table=True):
    """„Wenn Text … enthält → Kategorie …“; bei mehreren Treffern gewinnt (priority, id)."""

    __tablename__ = "mapping_rule"
    __table_args__ = (
        enum_check("match_type", MatchType),
        enum_check("match_field", MatchField),
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(
            ["target_category_id", "user_id"], ["category.id", "category.user_id"]
        ),
        Index("ix_mapping_rule_user_id_priority", "user_id", "priority", "id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    name: str | None = Field(default=None, max_length=100)
    pattern: str = Field(max_length=200)
    match_type: str = Field(default=MatchType.CONTAINS, sa_column=enum_column())
    match_field: str = Field(default=MatchField.ANY, sa_column=enum_column())
    case_sensitive: bool = False
    priority: int = 100
    target_category_id: int
    active: bool = True
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())
