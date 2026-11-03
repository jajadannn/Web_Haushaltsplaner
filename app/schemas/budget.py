from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Money, Name, PatchModel, ReadModel
from app.schemas.transaction import PositiveMoney

DueDay = Annotated[int, Field(ge=1, le=31)]
MatchText = Annotated[str, Field(min_length=2, max_length=100)]


class FixedCostCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    amount: PositiveMoney
    due_day: DueDay
    category_id: int | None = None
    match_text: MatchText | None = None
    start_date: date | None = None
    end_date: date | None = None
    active: bool = True

    @model_validator(mode="after")
    def _period(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date liegt vor start_date")
        return self


class FixedCostUpdate(PatchModel):
    _not_nullable = frozenset({"name", "amount", "due_day", "active"})
    name: Name | None = None
    amount: PositiveMoney | None = None
    due_day: DueDay | None = None
    category_id: int | None = None
    match_text: MatchText | None = None
    start_date: date | None = None
    end_date: date | None = None
    active: bool | None = None


class FixedCostRead(ReadModel):
    id: int
    name: str
    amount: Money
    due_day: int
    category_id: int | None
    match_text: str | None
    start_date: date | None
    end_date: date | None
    active: bool
    created_at: datetime
    updated_at: datetime


class MonthItem(BaseModel):
    """Eine Fixkost oder Kreditrate im Monat."""

    kind: Literal["fixed", "loan"]
    ref_id: int
    name: str
    amount: Money
    due_date: date
    status: Literal["paid", "open", "overdue"]
    paid_amount: Money | None
    paid_on: date | None


class BudgetMonth(BaseModel):
    """Monats-Spielraum: frei verfügbar = Einnahmen − Fixkosten − variable Ausgaben."""

    month: date
    as_of: date
    income: Money
    uncategorized_in: Money
    fixed_total: Money
    fixed_paid: Money
    variable_spent: Money
    available: Money
    days_left: int
    available_per_day: Money | None
    items: list[MonthItem]


class WallProfile(BaseModel):
    profile_id: int
    name: str
    available: Money
    income: Money
    fixed_total: Money
    variable_spent: Money
    available_per_day: Money | None
    timeline: list[MonthItem]
    upcoming: list[MonthItem]
    open_items: int


class WallLoan(BaseModel):
    loan_id: int
    profile_id: int
    profile_name: str
    name: str
    status: str
    remaining_debt: Money | None
    payoff_date: date | None
    remaining_installments: int
    next_due_date: date | None
    next_installment: Money | None


class WallView(BaseModel):
    generated_at: datetime
    month: date
    as_of: date
    days_left: int
    profiles: list[WallProfile]
    loans: list[WallLoan]
