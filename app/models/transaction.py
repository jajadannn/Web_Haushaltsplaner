from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import (
    created_at_column,
    enum_check,
    enum_column,
    nullable_timestamp,
    updated_at_column,
)


class TransactionKind(StrEnum):
    REGULAR = "regular"
    TRANSFER = "transfer"  # Umbuchung zwischen eigenen Konten: weder Einnahme noch Ausgabe


class ReviewStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    AUTO_CATEGORIZED = "auto_categorized"
    CONFIRMED = "confirmed"


class CategorySource(StrEnum):
    MANUAL = "manual"
    RULE = "rule"
    LOAN = "loan"
    NONE = "none"


class TransactionSource(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    LOAN = "loan"


class Transaction(SQLModel, table=True):
    __table_args__ = (
        enum_check("kind", TransactionKind),
        enum_check("review_status", ReviewStatus),
        enum_check("category_source", CategorySource),
        enum_check("source", TransactionSource),
        CheckConstraint("amount <> 0", name="amount_not_zero"),
        CheckConstraint("kind = 'regular' OR category_id IS NULL", name="transfer_without_category"),
        UniqueConstraint("id", "user_id"),
        # Konto und Kategorie müssen zum selben Profil gehören – in der DB abgesichert
        ForeignKeyConstraint(["account_id", "user_id"], ["account.id", "account.user_id"]),
        ForeignKeyConstraint(["category_id", "user_id"], ["category.id", "category.user_id"]),
        Index("ix_transaction_account_id_booking_date", "account_id", "booking_date"),
        Index("ix_transaction_user_id_booking_date", "user_id", "booking_date"),
        Index("ix_transaction_category_id", "category_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    account_id: int
    booking_date: date
    value_date: date | None = None
    amount: Decimal = Field(sa_type=Numeric(12, 2))
    description: str = Field(sa_type=Text)
    counterparty: str | None = Field(default=None, max_length=200)
    counterparty_iban: str | None = Field(default=None, max_length=34)
    kind: str = Field(default=TransactionKind.REGULAR, sa_column=enum_column())
    category_id: int | None = None
    review_status: str = Field(sa_column=enum_column())
    category_source: str = Field(sa_column=enum_column())
    # Regel, die die Kategorie gesetzt hat (Herkunft der Kategorisierung)
    applied_rule_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("mapping_rule.id", ondelete="SET NULL"), nullable=True),
    )
    source: str = Field(sa_column=enum_column())
    # Gegenbuchung einer über /transfers angelegten Umbuchung
    transfer_peer_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("transaction.id", ondelete="SET NULL"), nullable=True),
    )
    excluded_at: datetime | None = Field(default=None, sa_column=nullable_timestamp())
    excluded_reason: str | None = Field(default=None, max_length=500)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())

    splits: list[TransactionSplit] = Relationship(
        sa_relationship_kwargs={
            "order_by": "TransactionSplit.line_no",
            "cascade": "all, delete-orphan",
            "lazy": "selectin",
        }
    )


class TransactionSplit(SQLModel, table=True):
    """Aufteilung einer Buchung; die Summe der Zeilen entspricht immer dem Buchungsbetrag."""

    __tablename__ = "transaction_split"
    __table_args__ = (
        enum_check("kind", TransactionKind),
        CheckConstraint("amount <> 0", name="amount_not_zero"),
        CheckConstraint("kind = 'regular' OR category_id IS NULL", name="transfer_without_category"),
        UniqueConstraint("transaction_id", "line_no"),
        ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transaction.id", "transaction.user_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["category_id", "user_id"], ["category.id", "category.user_id"]),
    )

    id: int | None = Field(default=None, primary_key=True)
    transaction_id: int | None = Field(default=None, nullable=False)
    user_id: int = Field(foreign_key="app_user.id")
    line_no: int
    amount: Decimal = Field(sa_type=Numeric(12, 2))
    kind: str = Field(default=TransactionKind.REGULAR, sa_column=enum_column())
    category_id: int | None = Field(default=None, index=True)


# Sicht für alle Auswertungen: Split-Zeilen bzw. die ungeteilte Buchung selbst.
# Eigene MetaData, damit Alembic die View nicht als Tabelle anlegt (Migration erstellt sie per SQL).
_view_metadata = MetaData()
transaction_line = Table(
    "transaction_line",
    _view_metadata,
    Column("transaction_id", Integer),
    Column("split_id", Integer),
    Column("user_id", Integer),
    Column("account_id", Integer),
    Column("booking_date", Date),
    Column("amount", Numeric(12, 2)),
    Column("kind", String(20)),
    Column("category_id", Integer),
    Column("source", String(20)),
    Column("excluded_at", DateTime(timezone=True)),
)

TRANSACTION_LINE_VIEW_SQL = """
CREATE VIEW transaction_line AS
SELECT t.id AS transaction_id, NULL::integer AS split_id, t.user_id, t.account_id,
       t.booking_date, t.amount, t.kind, t.category_id, t.source, t.excluded_at
FROM "transaction" t
WHERE NOT EXISTS (SELECT 1 FROM transaction_split s WHERE s.transaction_id = t.id)
UNION ALL
SELECT t.id, s.id, t.user_id, t.account_id,
       t.booking_date, s.amount, s.kind, s.category_id, t.source, t.excluded_at
FROM "transaction" t
JOIN transaction_split s ON s.transaction_id = t.id
"""
