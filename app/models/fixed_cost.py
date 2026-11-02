from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import created_at_column, updated_at_column


class FixedCost(SQLModel, table=True):
    """Monatliche Fixkosten eines Profils (Miete, Strom, Abos …).

    Kreditraten gehören nicht hierher – sie kommen aus den Tilgungsplänen. Ob die Fixkost
    im Monat schon bezahlt ist, wird über Kategorie und/oder Suchtext an den Buchungen erkannt.
    """

    __tablename__ = "fixed_cost"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("due_day BETWEEN 1 AND 31", name="due_day_range"),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="period_order"),
        UniqueConstraint("user_id", "name"),
        ForeignKeyConstraint(["category_id", "user_id"], ["category.id", "category.user_id"]),
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
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())
