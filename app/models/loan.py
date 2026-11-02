from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models.base import created_at_column, enum_check, enum_column, updated_at_column


class LoanType(StrEnum):
    ANNUITY = "annuity"  # feste Rate, Zinsanteil sinkt
    INSTALLMENT = "installment"  # feste Tilgung, Rate sinkt (Ratenkredit/Tilgungsdarlehen)
    PRIVATE = "private"  # freie Rückzahlungen, optional vereinbarte Rate


class LoanStatus(StrEnum):
    ACTIVE = "active"
    PAID_OFF = "paid_off"


class ScheduleStatus(StrEnum):
    PLANNED = "planned"
    PAID = "paid"
    SKIPPED = "skipped"


class Loan(SQLModel, table=True):
    """Konditionen eines Kredits; Restschuld = −Saldo des zugehörigen `loan`-Kontos."""

    __table_args__ = (
        enum_check("loan_type", LoanType),
        enum_check("status", LoanStatus),
        CheckConstraint("annual_interest_rate >= 0", name="rate_not_negative"),
        CheckConstraint("extra_amount >= 0", name="extra_not_negative"),
        CheckConstraint("installment_amount IS NULL OR installment_amount > 0", name="installment_positive"),
        CheckConstraint("fixed_principal IS NULL OR fixed_principal > 0", name="principal_positive"),
        CheckConstraint("payment_day BETWEEN 1 AND 31", name="payment_day_range"),
        UniqueConstraint("account_id"),
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(["account_id", "user_id"], ["account.id", "account.user_id"]),
        ForeignKeyConstraint(
            ["payment_account_id", "user_id"], ["account.id", "account.user_id"]
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    account_id: int
    loan_type: str = Field(sa_column=enum_column())
    lender_name: str = Field(max_length=100)
    lender_iban: str | None = Field(default=None, max_length=34)
    payment_reference: str | None = Field(default=None, max_length=140)
    payment_account_id: int | None = None
    principal_original: Decimal | None = Field(default=None, sa_type=Numeric(12, 2))
    # Jahreszins in Prozent, z. B. 3.4500 = 3,45 % p. a.
    annual_interest_rate: Decimal = Field(sa_type=Numeric(6, 4))
    start_date: date | None = None
    first_due_date: date
    payment_day: int
    term_months: int | None = None
    # Annuität: Rate aus Zins + Tilgung (ohne extra); bei Privatkredit: vereinbarte Rate
    installment_amount: Decimal | None = Field(default=None, sa_type=Numeric(12, 2))
    # Tilgungsdarlehen: feste Tilgung je Rate
    fixed_principal: Decimal | None = Field(default=None, sa_type=Numeric(12, 2))
    extra_amount: Decimal = Field(default=Decimal("0.00"), sa_type=Numeric(12, 2))
    final_due_date: date | None = None
    fixed_rate_until: date | None = None
    status: str = Field(default=LoanStatus.ACTIVE, sa_column=enum_column())
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())


class LoanScheduleEntry(SQLModel, table=True):
    __tablename__ = "loan_schedule_entry"
    __table_args__ = (
        enum_check("status", ScheduleStatus),
        UniqueConstraint("loan_id", "seq"),
    )

    id: int | None = Field(default=None, primary_key=True)
    loan_id: int = Field(
        sa_column=Column(Integer, ForeignKey("loan.id", ondelete="CASCADE"), nullable=False)
    )
    seq: int
    due_date: date
    planned_interest: Decimal = Field(sa_type=Numeric(12, 2))
    planned_principal: Decimal = Field(sa_type=Numeric(12, 2))
    planned_extra: Decimal = Field(sa_type=Numeric(12, 2))
    planned_remaining_after: Decimal = Field(sa_type=Numeric(12, 2))
    status: str = Field(default=ScheduleStatus.PLANNED, sa_column=enum_column())
    payment_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("loan_payment.id", ondelete="SET NULL"), nullable=True),
    )

    @property
    def planned_installment(self) -> Decimal:
        return self.planned_interest + self.planned_principal + self.planned_extra


class LoanPayment(SQLModel, table=True):
    """Gebuchte Rate: verbindet Zahlung (z. B. Girokonto) und Tilgung auf dem Kreditkonto."""

    __tablename__ = "loan_payment"
    __table_args__ = (
        CheckConstraint("interest >= 0 AND principal >= 0 AND extra >= 0", name="parts_not_negative"),
        CheckConstraint("interest + principal + extra > 0", name="amount_positive"),
        UniqueConstraint("payment_transaction_id"),
        UniqueConstraint("loan_transaction_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    loan_id: int = Field(
        sa_column=Column(Integer, ForeignKey("loan.id", ondelete="CASCADE"), nullable=False)
    )
    payment_transaction_id: int = Field(foreign_key="transaction.id")
    # Gegenbuchung +Tilgung auf dem Kreditkonto (fehlt, wenn nur Zinsen gezahlt wurden)
    loan_transaction_id: int | None = Field(default=None, foreign_key="transaction.id")
    # True, wenn die Zahlung beim Buchen der Rate neu angelegt wurde (beim Storno löschen)
    owns_payment_transaction: bool
    booking_date: date
    interest: Decimal = Field(sa_type=Numeric(12, 2))
    principal: Decimal = Field(sa_type=Numeric(12, 2))
    extra: Decimal = Field(sa_type=Numeric(12, 2))
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
