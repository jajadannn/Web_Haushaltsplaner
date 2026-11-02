from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import (
    created_at_column,
    enum_check,
    enum_column,
    nullable_timestamp,
    updated_at_column,
)


class ImportFormat(StrEnum):
    CSV = "csv"
    OFX = "ofx"
    MT940 = "mt940"


class SignMode(StrEnum):
    SIGNED = "signed"  # eine Betragsspalte mit Vorzeichen
    DEBIT_CREDIT_COLUMNS = "debit_credit_columns"  # getrennte Soll-/Haben-Spalten
    INDICATOR_COLUMN = "indicator_column"  # Betrag + Kennzeichen (z. B. S/H)


class BatchStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    DONE = "done"
    FAILED = "failed"


class ArchiveState(StrEnum):
    PENDING = "pending"
    DONE = "done"
    ERROR = "error"


class BatchSource(StrEnum):
    UPLOAD = "upload"
    WATCHER = "watcher"


class RowDecision(StrEnum):
    NEW = "new"
    DUPLICATE = "duplicate"
    AMBIGUOUS = "ambiguous"  # mögliche Dublette – der Nutzer entscheidet
    BEFORE_OPENING = "before_opening"  # vor dem Stichtag des Kontos
    SKIPPED = "skipped"  # z. B. vorgemerkte Umsätze


class MatchKind(StrEnum):
    EXTERNAL_ID = "external_id"  # gleiche Bank-ID
    FINGERPRINT = "fingerprint"  # gleicher Text, Betrag und Tag wie ein früherer Import
    SIMILAR = "similar"  # gleicher Betrag, gleiches/ähnliches Datum


class RowResolution(StrEnum):
    IMPORT = "import"
    DUPLICATE = "duplicate"
    SKIP = "skip"


class ImportProfile(SQLModel, table=True):
    """Dateiformat einer Bank; gilt für alle Konten dieser Bank."""

    __tablename__ = "import_profile"
    __table_args__ = (
        enum_check("format", ImportFormat),
        enum_check("sign_mode", SignMode),
        UniqueConstraint("user_id", "name"),
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(
            ["institution_id", "user_id"], ["institution.id", "institution.user_id"]
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    institution_id: int
    name: str = Field(max_length=100)
    format: str = Field(sa_column=enum_column())
    version: int = Field(default=1)
    # CSV-Optionen (für OFX/MT940 ohne Bedeutung)
    delimiter: str = Field(default=";", max_length=1)
    encoding: str = Field(default="utf-8", max_length=20)
    skip_rows: int = Field(default=0)
    column_map: dict = Field(default_factory=dict, sa_type=JSONB)
    date_format: str = Field(default="%d.%m.%Y", max_length=20)
    decimal_sep: str = Field(default=",", max_length=1)
    thousands_sep: str = Field(default=".", max_length=1)
    sign_mode: str = Field(default=SignMode.SIGNED, sa_column=enum_column())
    debit_indicators: list = Field(default_factory=list, sa_type=JSONB)
    pending_values: list = Field(default_factory=list, sa_type=JSONB)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())


class WatchFolder(SQLModel, table=True):
    """Unterordner der Import-Inbox; Dateien darin gehören zu Profil und ggf. Konto."""

    __tablename__ = "watch_folder"
    __table_args__ = (
        CheckConstraint("subdir ~ '^[A-Za-z0-9_-]+$'", name="subdir_simple"),
        ForeignKeyConstraint(
            ["import_profile_id", "user_id"], ["import_profile.id", "import_profile.user_id"]
        ),
        ForeignKeyConstraint(["account_id", "user_id"], ["account.id", "account.user_id"]),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    subdir: str = Field(max_length=64, unique=True)
    import_profile_id: int
    # Ohne Konto wird über IBAN/Kontoreferenz in der Datei zugeordnet
    account_id: int | None = None
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())


class ImportBatch(SQLModel, table=True):
    __tablename__ = "import_batch"
    __table_args__ = (
        enum_check("status", BatchStatus),
        enum_check("archive_state", ArchiveState),
        enum_check("source", BatchSource),
        ForeignKeyConstraint(
            ["import_profile_id", "user_id"], ["import_profile.id", "import_profile.user_id"]
        ),
        ForeignKeyConstraint(["account_id", "user_id"], ["account.id", "account.user_id"]),
        # Dieselbe Datei wird je Profil und gewähltem Zielkonto nur einmal (erfolgreich) verarbeitet
        Index(
            "uq_import_batch_file",
            "user_id",
            "import_profile_id",
            text("coalesce(target_account_id, 0)"),
            "file_sha256",
            unique=True,
            postgresql_where=text("status <> 'failed'"),
        ),
        ForeignKeyConstraint(["target_account_id", "user_id"], ["account.id", "account.user_id"]),
        Index("ix_import_batch_status", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    import_profile_id: int
    # Erkanntes Konto (bei einer Datei für genau ein Konto)
    account_id: int | None = None
    # Vom Nutzer gewähltes Zielkonto (Upload/Watch-Ordner) – Teil der Dateiidentität
    target_account_id: int | None = None
    profile_version: int
    parser_version: str = Field(max_length=20)
    original_filename: str = Field(max_length=255)
    stored_path: str = Field(sa_type=Text)
    file_sha256: str = Field(max_length=64)
    source: str = Field(sa_column=enum_column())
    status: str = Field(default=BatchStatus.QUEUED, sa_column=enum_column())
    attempt: int = Field(default=0)
    started_at: datetime | None = Field(default=None, sa_column=nullable_timestamp())
    heartbeat_at: datetime | None = Field(default=None, sa_column=nullable_timestamp())
    finished_at: datetime | None = Field(default=None, sa_column=nullable_timestamp())
    errors: list = Field(default_factory=list, sa_type=JSONB)
    archive_state: str = Field(default=ArchiveState.PENDING, sa_column=enum_column())
    rows_total: int = Field(default=0)
    rows_new: int = Field(default=0)
    rows_duplicate: int = Field(default=0)
    rows_review: int = Field(default=0)
    rows_skipped: int = Field(default=0)
    # Vorgemerkte Umsätze, die der Parser übersprungen hat (kommen mit dem nächsten Export)
    rows_pending: int = Field(default=0)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())


class ImportRow(SQLModel, table=True):
    """Eine Zeile der Datei: Rohdaten, normalisierte Werte und Entscheidung."""

    __tablename__ = "import_row"
    __table_args__ = (
        enum_check("decision", RowDecision),
        CheckConstraint(
            "resolution IS NULL OR resolution IN ('import', 'duplicate', 'skip')", name="resolution"
        ),
        UniqueConstraint("batch_id", "row_no"),
    )

    id: int | None = Field(default=None, primary_key=True)
    batch_id: int = Field(
        sa_column=Column(Integer, ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False)
    )
    row_no: int
    account_id: int = Field(foreign_key="account.id")
    raw: dict = Field(default_factory=dict, sa_type=JSONB)
    booking_date: date
    value_date: date | None = None
    amount: Decimal = Field(sa_type=Numeric(12, 2))
    description: str = Field(sa_type=Text)
    counterparty: str | None = Field(default=None, max_length=200)
    counterparty_iban: str | None = Field(default=None, max_length=34)
    external_id: str | None = Field(default=None, max_length=255)
    fingerprint: str = Field(max_length=64)
    decision: str = Field(sa_column=enum_column())
    match_kind: str | None = Field(default=None, sa_column=enum_column(nullable=True))
    resolution: str | None = Field(default=None, sa_column=enum_column(nullable=True))
    note: str | None = Field(default=None, max_length=500)
    matched_transaction_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("transaction.id", ondelete="SET NULL"), nullable=True),
    )
    created_transaction_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("transaction.id", ondelete="SET NULL"), nullable=True),
    )
    suggested_loan_entry_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("loan_schedule_entry.id", ondelete="SET NULL"), nullable=True
        ),
    )


class TransactionImportLink(SQLModel, table=True):
    """Importidentität einer Buchung – bleibt auch bei Ausschluss oder Änderungen erhalten."""

    __tablename__ = "transaction_import_link"
    __table_args__ = (
        # Nur belastbare Bank-IDs sind eindeutig; der Fingerprint ist bloß eine Suchhilfe
        Index(
            "uq_transaction_import_link_external_id",
            "account_id",
            "id_namespace",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index("ix_transaction_import_link_fingerprint", "account_id", "fingerprint"),
    )

    id: int | None = Field(default=None, primary_key=True)
    transaction_id: int = Field(
        sa_column=Column(Integer, ForeignKey("transaction.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    import_row_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("import_row.id", ondelete="SET NULL"), nullable=True),
    )
    account_id: int = Field(foreign_key="account.id")
    id_namespace: str = Field(max_length=20)
    external_id: str | None = Field(default=None, max_length=255)
    fingerprint: str = Field(max_length=64)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
