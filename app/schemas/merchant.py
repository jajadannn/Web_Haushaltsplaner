from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Name, PatchModel, ReadModel


class MerchantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    kind: Literal["merchant", "payment_provider"] = "merchant"


class MerchantUpdate(PatchModel):
    _not_nullable = frozenset({"name", "kind"})
    name: Name | None = None
    kind: Literal["merchant", "payment_provider"] | None = None


class MerchantRead(ReadModel):
    id: int
    name: str
    kind: str
    created_at: datetime


class AliasCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_type: Literal["iban", "reference", "name"]
    value: Annotated[str, Field(min_length=2, max_length=140)]
    contract_id: int | None = None


class AliasRead(ReadModel):
    id: int
    merchant_id: int
    contract_id: int | None
    match_type: str
    value: str
    confirmed: bool
    source: str


class ContractCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Name
    reference: Annotated[str, Field(max_length=140)] | None = None


class ContractRead(ReadModel):
    id: int
    merchant_id: int
    label: str
    reference: str | None
    fixed_cost_id: int | None
    notice_period: str | None
    term_end: str | None
