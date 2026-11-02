from enum import StrEnum

from sqlalchemy import CheckConstraint, Column, DateTime, MetaData, String, func
from sqlmodel import SQLModel

# Feste Constraint-Namen, damit Alembic-Migrationen stabil und lesbar bleiben
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata: MetaData = SQLModel.metadata


def enum_column(length: int = 20, *, nullable: bool = False) -> Column:
    """Enums als VARCHAR + CHECK statt nativer PG-Enums (einfachere Migrationen)."""
    return Column(String(length), nullable=nullable)


def enum_check(column: str, enum: type[StrEnum]) -> CheckConstraint:
    values = ", ".join(f"'{e.value}'" for e in enum)
    return CheckConstraint(f"{column} IN ({values})", name=column)


def created_at_column() -> Column:
    return Column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_at_column() -> Column:
    return Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


def nullable_timestamp() -> Column:
    return Column(DateTime(timezone=True), nullable=True)


