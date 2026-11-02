from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, true
from sqlmodel import Field, SQLModel

from app.models.base import created_at_column, enum_check, enum_column


class CategoryType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class Category(SQLModel, table=True):
    __table_args__ = (
        enum_check("type", CategoryType),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        UniqueConstraint("id", "user_id"),
        UniqueConstraint("id", "user_id", "type"),
        UniqueConstraint("user_id", "parent_id", "name", postgresql_nulls_not_distinct=True),
        UniqueConstraint("user_id", "system_key"),
        # Elternkategorie: gleiches Profil UND gleicher Typ – in der DB abgesichert
        ForeignKeyConstraint(
            ["parent_id", "user_id", "type"],
            ["category.id", "category.user_id", "category.type"],
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    name: str = Field(max_length=100)
    type: str = Field(sa_column=enum_column())
    icon: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, max_length=7)
    parent_id: int | None = Field(default=None)
    active: bool = Field(default=True, sa_column_kwargs={"server_default": true()})
    # Vom System benötigte Kategorien (z. B. loan_interest); nicht löschbar
    system_key: str | None = Field(default=None, max_length=50)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
