from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.models import AccountType, LoanStatus
from app.schemas.common import Money


class Flows(BaseModel):
    income: Money
    expenses: Money
    uncategorized_in: Money
    uncategorized_out: Money
    net: Money
    cash_in: Money
    cash_out: Money


class MonthFlows(Flows):
    month: date


class AccountBalance(BaseModel):
    account_id: int
    name: str
    type: AccountType
    institution_id: int | None
    archived: bool
    balance: Money | None
    history_incomplete: bool


class InstitutionBalance(BaseModel):
    institution_id: int | None
    name: str
    balance: Money


class SummaryReport(BaseModel):
    date_from: date
    date_to: date
    accounts: list[AccountBalance]
    institutions: list[InstitutionBalance]
    assets: Money
    liabilities: Money
    net_worth: Money
    movements: Flows
    months: list[MonthFlows]


class CategoryItem(BaseModel):
    category_id: int
    name: str
    parent_id: int | None
    root_id: int
    gross: Money
    refunds: Money
    net: Money
    own_net: Money
    share: Decimal | None


class CategoryReport(BaseModel):
    date_from: date
    date_to: date
    type: Literal["income", "expense"]
    items: list[CategoryItem]
    total_net: Money
    share_basis: Money
    uncategorized: Money


class TrendMonth(BaseModel):
    month: date
    income: Money
    expenses: Money
    uncategorized_in: Money
    uncategorized_out: Money
    net: Money
    coverage: Literal["unknown"]


class TrendReport(BaseModel):
    months: list[TrendMonth]
    category_id: int | None


class RemainingAt(BaseModel):
    month_end: date
    remaining_debt: Money | None


class YearInterest(BaseModel):
    """Zinskosten eines Jahres: `interest` = `paid` (mit Raten gezahlt) + `charged` (der Schuld zugeschlagen)."""

    year: int
    interest: Money
    paid: Money
    charged: Money


class LoanReportItem(BaseModel):
    loan_id: int
    name: str
    status: LoanStatus
    remaining_debt: Money | None
    next_installment: Money | None
    remaining_by_month: list[RemainingAt]
    interest_paid_by_year: list[YearInterest]


class LoanReport(BaseModel):
    """`remaining_debt` und die Monatswerte gelten zum Stichtag `until`; Status, nächste Rate und
    `monthly_burden` sind der aktuelle Stand vom `current_as_of`."""

    loans: list[LoanReportItem]
    monthly_burden: Money
    current_as_of: date
