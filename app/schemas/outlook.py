from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.budget import DueDay, IntervalMonths, MatchText
from app.schemas.common import Money, Name, PatchModel, ReadModel
from app.schemas.transaction import PositiveMoney


class ExpectedIncomeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    amount: PositiveMoney
    amount_min: PositiveMoney | None = None
    amount_max: PositiveMoney | None = None
    interval_months: IntervalMonths = 1
    due_day: DueDay
    first_due_date: date | None = None
    account_id: int | None = None
    category_id: int | None = None
    match_text: MatchText | None = None
    active: bool = True

    @model_validator(mode="after")
    def _range(self):
        if self.amount_min and self.amount_max and self.amount_min > self.amount_max:
            raise ValueError("amount_min ist größer als amount_max")
        return self


class ExpectedIncomeUpdate(PatchModel):
    _not_nullable = frozenset({"name", "amount", "interval_months", "due_day", "active"})
    name: Name | None = None
    amount: PositiveMoney | None = None
    amount_min: PositiveMoney | None = None
    amount_max: PositiveMoney | None = None
    interval_months: IntervalMonths | None = None
    due_day: DueDay | None = None
    first_due_date: date | None = None
    account_id: int | None = None
    category_id: int | None = None
    match_text: MatchText | None = None
    active: bool | None = None


class ExpectedIncomeRead(ReadModel):
    id: int
    name: str
    amount: Money
    amount_min: Money | None
    amount_max: Money | None
    interval_months: int
    due_day: int
    first_due_date: date | None
    account_id: int | None
    category_id: int | None
    match_text: str | None
    active: bool
    created_at: datetime


class ForecastEvent(BaseModel):
    date: date
    name: str
    amount: Money
    kind: Literal["fixed_cost", "expected_income", "loan_installment"]
    expected: bool
    ref_id: int
    range: list[Money] | None = None
    balance_after: Money


class ForecastPoint(BaseModel):
    date: date
    balance: Money


class Forecast(BaseModel):
    """Vorschau: tatsächlicher Kontostand heute plus erwartete (noch nicht gebuchte) Ereignisse."""

    account_id: int
    as_of: date
    until: date
    start_balance: Money
    events: list[ForecastEvent]
    end_balance: Money
    lowest: ForecastPoint
