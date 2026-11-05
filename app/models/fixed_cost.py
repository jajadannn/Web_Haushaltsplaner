from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import created_at_column, updated_at_column


class FixedCost(SQLModel, table=True):
    """Fixkosten eines Profils (Miete, Strom, Abos, Versicherungen …).

    Rhythmus `interval_months` (1, 3, 6, 12); bei mehr als einem Monat legt `first_due_date`
    die Fälligkeitsmonate fest. Kreditraten gehören nicht hierher – sie kommen aus den
    Tilgungsplänen. Bezahlt ist eine Fälligkeit, wenn eine Zahlung fest verknüpft ist
    (`FixedCostPayment`), sonst erkennt der Monatsplan sie über Kategorie und/oder Suchtext.
    """

    __tablename__ = "fixed_cost"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("due_day BETWEEN 1 AND 31", name="due_day_range"),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="period_order"),
        CheckConstraint("interval_months IN (1, 3, 6, 12)", name="interval_months"),
        CheckConstraint("interval_months = 1 OR first_due_date IS NOT NULL", name="first_due_date_required"),
        UniqueConstraint("user_id", "name"),
        ForeignKeyConstraint(["category_id", "user_id"], ["category.id", "category.user_id"]),
        ForeignKeyConstraint(["account_id", "user_id"], ["account.id", "account.user_id"]),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    name: str = Field(max_length=100)
    amount: Decimal = Field(sa_type=Numeric(12, 2))
    due_day: int
    category_id: int | None = None
    # Teiltext in Verwendungszweck oder Gegenpartei, der die Zahlung erkennt (z. B. "Stadtwerke")
    match_text: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    active: bool = True
    interval_months: int = 1
    first_due_date: date | None = None
    account_id: int | None = None  # Zahlkonto (für die Kontovorschau)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())


class FixedCostPayment(SQLModel, table=True):
    """Feste Verknüpfung einer Buchungszeile mit einer Fälligkeit einer Fixkost.

    Eine Buchungszeile (Buchung oder Split) gehört höchstens zu einer Fixkost, eine Fälligkeit
    (Monat) hat höchstens eine Zahlung.
    """

    __tablename__ = "fixed_cost_payment"
    __table_args__ = (
        UniqueConstraint("transaction_id", "split_id", postgresql_nulls_not_distinct=True),
        UniqueConstraint("fixed_cost_id", "due_month"),
        CheckConstraint("source IN ('manual', 'suggestion', 'auto')", name="source"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", ondelete="CASCADE")
    fixed_cost_id: int = Field(foreign_key="fixed_cost.id", ondelete="CASCADE")
    transaction_id: int = Field(foreign_key="transaction.id", ondelete="CASCADE")
    split_id: int | None = Field(default=None, foreign_key="transaction_split.id", ondelete="CASCADE")
    due_month: date
    source: str = Field(default="manual", max_length=20)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
