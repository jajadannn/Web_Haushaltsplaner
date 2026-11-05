from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.loan import LoanStatus, LoanType, ScheduleStatus
from app.schemas.common import Money, Name, PatchModel
from app.schemas.transaction import Description, PositiveMoney

InterestRate = Annotated[
    Decimal, Field(ge=0, lt=100, max_digits=6, decimal_places=4, allow_inf_nan=False)
]
PaymentDay = Annotated[int, Field(ge=1, le=31)]
Term = Annotated[int, Field(ge=1, le=600)]


def _not_negative(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("Betrag darf nicht negativ sein")
    return value


NonNegativeMoney = Annotated[Money, AfterValidator(_not_negative)]


class LoanCreate(BaseModel):
    """Neuer oder laufender Kredit.

    - Laufender Kredit: `current_balance` = aktuelle Restschuld am Stichtag `balance_date`.
    - Neuer Kredit mit Auszahlung: zusätzlich `disbursement_account_id` – die Auszahlung
      wird am Stichtag als Umbuchung Kreditkonto → Girokonto gebucht.
    - Annuität: `installment_amount` (Zins + Tilgung) und/oder `term_months`.
    - Tilgungsdarlehen: `fixed_principal` und/oder `term_months`.
    - Privatkredit: optional `installment_amount` als vereinbarte Rate.
    """

    model_config = ConfigDict(extra="forbid")
    name: Name
    loan_type: LoanType
    lender_name: Name
    institution_id: int | None = None
    bank_account_ref: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    lender_iban: str | None = Field(default=None, max_length=42)
    payment_reference: Annotated[str, Field(max_length=140)] | None = None
    payment_account_id: int | None = None
    annual_interest_rate: InterestRate
    current_balance: PositiveMoney
    balance_date: date
    first_due_date: date | None = None
    payment_day: PaymentDay | None = None
    term_months: Term | None = None
    installment_amount: PositiveMoney | None = None
    fixed_principal: PositiveMoney | None = None
    extra_amount: NonNegativeMoney = Decimal("0.00")
    principal_original: PositiveMoney | None = None
    start_date: date | None = None
    fixed_rate_until: date | None = None
    disbursement_account_id: int | None = None


class LoanUpdate(PatchModel):
    """Änderungen an Konditionen wirken auf alle noch offenen Raten."""

    _not_nullable = frozenset({"name", "lender_name", "annual_interest_rate", "payment_day", "extra_amount"})
    name: Name | None = None
    lender_name: Name | None = None
    lender_iban: str | None = Field(default=None, max_length=42)
    payment_reference: Annotated[str, Field(max_length=140)] | None = None
    payment_account_id: int | None = None
    annual_interest_rate: InterestRate | None = None
    payment_day: PaymentDay | None = None
    term_months: Term | None = None
    installment_amount: PositiveMoney | None = None
    fixed_principal: PositiveMoney | None = None
    extra_amount: NonNegativeMoney | None = None
    fixed_rate_until: date | None = None


class LoanRead(BaseModel):
    id: int
    name: str
    account_id: int
    institution_id: int | None
    loan_type: LoanType
    status: LoanStatus
    lender_name: str
    lender_iban: str | None
    payment_reference: str | None
    payment_account_id: int | None
    annual_interest_rate: Decimal
    first_due_date: date
    payment_day: int
    term_months: int | None
    installment_amount: Money | None
    fixed_principal: Money | None
    extra_amount: Money
    principal_original: Money | None
    start_date: date | None
    fixed_rate_until: date | None
    final_due_date: date | None
    remaining_debt: Money
    principal_repaid: Money  # Summe der tatsächlich gezahlten Tilgungsanteile
    next_due_date: date | None
    next_installment: Money | None
    open_installments: int
    overdue_installments: int
    created_at: datetime


class ScheduleEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seq: int
    due_date: date
    planned_installment: Money
    planned_interest: Money
    planned_principal: Money
    planned_extra: Money
    planned_remaining_after: Money
    status: ScheduleStatus
    overdue: bool = False
    payment_id: int | None


class LoanPaymentCreate(BaseModel):
    """Rate buchen – entweder eine vorhandene Zahlung verknüpfen (`transaction_id`) oder
    eine neue Zahlung anlegen (`booking_date` + `amount`, Konto standardmäßig das Zahlkonto).

    Ohne Angaben schlägt das System die Aufteilung vor (zuerst Gebühren, dann Zinsen,
    Rest Tilgung). `interest`/`principal`/`extra` überschreiben den Vorschlag (alle drei
    angeben; Summe = Zahlbetrag), z. B. nach den Zahlen der Bank.
    """

    model_config = ConfigDict(extra="forbid")
    transaction_id: int | None = None
    account_id: int | None = None
    booking_date: date | None = None
    amount: PositiveMoney | None = None
    description: Description | None = None
    schedule_seq: int | None = None
    interest: NonNegativeMoney | None = None
    principal: NonNegativeMoney | None = None
    extra: NonNegativeMoney | None = None


class LoanPaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    loan_id: int
    payment_transaction_id: int
    loan_transaction_id: int | None
    booking_date: date
    interest: Money
    principal: Money
    extra: Money
    schedule_seq: int | None = None


class LoanChargeCreate(BaseModel):
    """Zinsen/Gebühren, die direkt dem Kreditkonto belastet werden (erhöhen die Restschuld)."""

    model_config = ConfigDict(extra="forbid")
    booking_date: date
    amount: PositiveMoney
    charge_type: Literal["interest", "fee"]
    description: Description | None = None


class UpcomingInstallment(BaseModel):
    loan_id: int
    loan_name: str
    seq: int
    due_date: date
    planned_installment: Money
    payment_account_id: int | None
    overdue: bool


class LoanYearSummary(BaseModel):
    year: int
    payments: int
    interest_paid: Money
    principal_paid: Money
    extra_paid: Money
    interest_charged: Money
    fees_charged: Money
    remaining_debt_end_of_year: Money | None
