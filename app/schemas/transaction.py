from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.transaction import (
    CategorySource,
    ReviewStatus,
    TransactionKind,
    TransactionSource,
)
from app.schemas.common import Money, PatchModel, ReadModel


def _not_zero(value: Decimal) -> Decimal:
    if value == 0:
        raise ValueError("Betrag darf nicht 0 sein")
    return value


def _positive(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("Betrag muss positiv sein")
    return value


NonZeroMoney = Annotated[Money, AfterValidator(_not_zero)]
PositiveMoney = Annotated[Money, AfterValidator(_positive)]
Description = Annotated[str, Field(min_length=1, max_length=1000)]
Counterparty = Annotated[str, Field(max_length=200)]


class SplitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: NonZeroMoney
    kind: TransactionKind = TransactionKind.REGULAR
    category_id: int | None = None


class SplitRead(ReadModel):
    id: int
    line_no: int
    amount: Money
    kind: TransactionKind
    category_id: int | None


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: int
    booking_date: date
    value_date: date | None = None
    amount: NonZeroMoney
    description: Description
    counterparty: Counterparty | None = None
    counterparty_iban: str | None = Field(default=None, max_length=42)
    kind: TransactionKind = TransactionKind.REGULAR
    category_id: int | None = None
    splits: list[SplitIn] | None = None


class TransactionUpdate(PatchModel):
    _not_nullable = frozenset({"account_id", "booking_date", "amount", "description", "kind"})
    account_id: int | None = None
    booking_date: date | None = None
    value_date: date | None = None
    amount: NonZeroMoney | None = None
    description: Description | None = None
    counterparty: Counterparty | None = None
    counterparty_iban: str | None = Field(default=None, max_length=42)
    kind: TransactionKind | None = None
    category_id: int | None = None
    # Ersetzt alle Splits; null oder [] entfernt die Aufteilung
    splits: list[SplitIn] | None = None


class TransactionExclude(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class TransactionRead(ReadModel):
    id: int
    account_id: int
    booking_date: date
    value_date: date | None
    amount: Money
    description: str
    counterparty: str | None
    counterparty_iban: str | None
    kind: TransactionKind
    category_id: int | None
    review_status: ReviewStatus
    category_source: CategorySource
    applied_rule_id: int | None
    source: TransactionSource
    transfer_peer_id: int | None
    excluded_at: datetime | None
    excluded_reason: str | None
    ai_note: str | None
    created_at: datetime
    updated_at: datetime
    splits: list[SplitRead]


class TransactionPage(BaseModel):
    items: list[TransactionRead]
    total: int
    limit: int
    offset: int


class TransferCreate(BaseModel):
    """Umbuchung zwischen zwei eigenen Konten – legt beide Seiten in einem Schritt an."""

    model_config = ConfigDict(extra="forbid")
    from_account_id: int
    to_account_id: int
    booking_date: date
    amount: PositiveMoney
    description: Description = "Umbuchung"


class TransferRead(BaseModel):
    outgoing: TransactionRead
    incoming: TransactionRead
