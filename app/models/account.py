from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import (
    created_at_column,
    enum_check,
    enum_column,
    nullable_timestamp,
    updated_at_column,
)


class AccountType(StrEnum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    LOAN = "loan"


class Account(SQLModel, table=True):
    __table_args__ = (
        enum_check("type", AccountType),
        CheckConstraint("currency = 'EUR'", name="currency_eur"),
        UniqueConstraint("id", "user_id"),
        UniqueConstraint("user_id", "name"),
        UniqueConstraint("user_id", "iban_normalized"),
        UniqueConstraint("institution_id", "bank_account_ref"),
        ForeignKeyConstraint(
            ["institution_id", "user_id"], ["institution.id", "institution.user_id"]
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    institution_id: int | None = Field(default=None)
    name: str = Field(max_length=100)
    type: str = Field(sa_column=enum_column())
    currency: str = Field(default="EUR", max_length=3)
    # Saldo zu BEGINN von opening_balance_date
    opening_balance: Decimal = Field(sa_type=Numeric(12, 2))
    opening_balance_date: date
    iban_normalized: str | None = Field(default=None, max_length=34)
    bank_account_ref: str | None = Field(default=None, max_length=64)
    archived_at: datetime | None = Field(default=None, sa_column=nullable_timestamp())
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())
