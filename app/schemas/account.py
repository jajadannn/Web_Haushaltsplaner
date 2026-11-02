from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import AccountType
from app.schemas.common import Money, Name, PatchModel, ReadModel

AccountRef = Annotated[str, Field(min_length=1, max_length=64)]


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    type: AccountType
    institution_id: int | None = None
    currency: Literal["EUR"] = "EUR"
    opening_balance: Money
    opening_balance_date: date
    iban: str | None = Field(default=None, max_length=42)
    bank_account_ref: AccountRef | None = None


class AccountUpdate(PatchModel):
    _not_nullable = frozenset({"name", "type", "opening_balance", "opening_balance_date"})
    name: Name | None = None
    type: AccountType | None = None
    institution_id: int | None = None
    opening_balance: Money | None = None
    opening_balance_date: date | None = None
    iban: str | None = Field(default=None, max_length=42)
    bank_account_ref: AccountRef | None = None


class AccountRead(ReadModel):
    id: int
    name: str
    type: AccountType
    institution_id: int | None
    currency: str
    opening_balance: Money
    opening_balance_date: date
    iban: str | None = Field(validation_alias="iban_normalized")
    bank_account_ref: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Berechneter Saldo am Ende von balance_date; None = vor dem Stichtag nicht verfügbar
    balance: Money | None = None
    balance_date: date | None = None
