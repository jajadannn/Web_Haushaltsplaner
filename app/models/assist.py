"""Bausteine des KI-Ausbaus: Vorschläge, Änderungsverlauf, Profil-Einstellungen, KI-Aufträge.

- `Suggestion`: jeder automatisch erkannte Vorschlag (Fixkost, Regel, Erstattung …) mit Belegen,
  Status und Ergebnis. `(user_id, kind, fingerprint)` ist eindeutig – eine Ablehnung bleibt so
  gespeichert und derselbe Fall erscheint nicht ständig wieder.
- `ChangeLog`: vorher/nachher jeder Änderung, die aus einem Vorschlag entsteht (Rücknahme).
- `ProfileSetting`: Einstellungen je Profil (z. B. Automatik an/aus).
- `AiJob`/`AiCache`: Warteschlange und Zwischenspeicher für KI-Anfragen.
- `AnalysisState`: wann ein Profil nach einem Import neu ausgewertet werden muss.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import created_at_column, enum_check, enum_column, nullable_timestamp, updated_at_column


class SuggestionKind(StrEnum):
    FIXED_COST_NEW = "fixed_cost_new"
    FIXED_COST_CHANGE = "fixed_cost_change"
    RULE = "rule"
    MISSING_PAYMENT = "missing_payment"
    UNUSUAL_PAYMENT = "unusual_payment"
    REFUND_MATCH = "refund_match"
    TRANSFER_MATCH = "transfer_match"
    INCOME_SERIES = "income_series"
    ANNUAL_COST = "annual_cost"
    CONSISTENCY = "consistency"
    QUESTION = "question"
    SPLIT_TEMPLATE = "split_template"
    RECEIPT_MATCH = "receipt_match"
    CONTRACT_DRAFT = "contract_draft"
    IMPORT_PROFILE_FIX = "import_profile_fix"


class SuggestionStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AUTO_APPLIED = "auto_applied"
    DRY_RUN = "dry_run"  # Probelauf: wäre automatisch übernommen worden
    REVERTED = "reverted"
    STALE = "stale"


class Suggestion(SQLModel, table=True):
    __tablename__ = "suggestion"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "fingerprint"),
        enum_check("kind", SuggestionKind),
        enum_check("status", SuggestionStatus),
        Index("ix_suggestion_user_id_status", "user_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", ondelete="CASCADE")
    kind: str = Field(sa_column=enum_column(30))
    status: str = Field(default=SuggestionStatus.OPEN, sa_column=enum_column(20))
    fingerprint: str = Field(max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    evidence: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    reason: str = Field(default="", max_length=1000)
    generator: str = Field(default="", max_length=100)
    priority: int = 0  # höher = wichtiger
    data_as_of: datetime | None = Field(default=None, sa_column=nullable_timestamp())
    result_type: str | None = Field(default=None, max_length=30)
    result_id: int | None = None
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())
    decided_at: datetime | None = Field(default=None, sa_column=nullable_timestamp())


class ChangeActor(StrEnum):
    USER = "user"
    AUTO = "auto"


class ChangeLog(SQLModel, table=True):
    __tablename__ = "change_log"
    __table_args__ = (
        enum_check("actor", ChangeActor),
        Index("ix_change_log_user_id_created_at", "user_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", ondelete="CASCADE")
    object_type: str = Field(max_length=30)
    object_id: int
    action: str = Field(max_length=20)  # create | update
    before: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    after: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    suggestion_id: int | None = Field(default=None, foreign_key="suggestion.id", ondelete="SET NULL")
    actor: str = Field(default=ChangeActor.USER, sa_column=enum_column(10))
    reverted_at: datetime | None = Field(default=None, sa_column=nullable_timestamp())
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())


class ProfileSetting(SQLModel, table=True):
    __tablename__ = "profile_setting"

    user_id: int = Field(foreign_key="app_user.id", primary_key=True, ondelete="CASCADE")
    key: str = Field(primary_key=True, max_length=60)
    value: Any = Field(sa_column=Column(JSONB, nullable=False))
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())


class AiJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class AiJob(SQLModel, table=True):
    """Eine KI-Anfrage im Hintergrund (Anreicherung eines Vorschlags, Belegauslesen …)."""

    __tablename__ = "ai_job"
    __table_args__ = (
        enum_check("status", AiJobStatus),
        UniqueConstraint("kind", "ref_type", "ref_id"),
        Index("ix_ai_job_status_id", "status", "id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", ondelete="CASCADE")
    kind: str = Field(max_length=40)
    ref_type: str = Field(max_length=30)
    ref_id: int
    status: str = Field(default=AiJobStatus.QUEUED, sa_column=enum_column(10))
    attempts: int = 0
    lease_until: datetime | None = Field(default=None, sa_column=nullable_timestamp())
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    error: str | None = Field(default=None, max_length=500)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
    updated_at: datetime | None = Field(default=None, sa_column=updated_at_column())


class AiCache(SQLModel, table=True):
    __tablename__ = "ai_cache"

    key: str = Field(primary_key=True, max_length=64)
    result: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())


class AnalysisState(SQLModel, table=True):
    """Nach einem Import fällige Auswertung je Profil (Fixkosten, Erstattungen, …)."""

    __tablename__ = "analysis_state"

    user_id: int = Field(foreign_key="app_user.id", primary_key=True, ondelete="CASCADE")
    due_at: datetime | None = Field(default=None, sa_column=nullable_timestamp())
    last_run_at: datetime | None = Field(default=None, sa_column=nullable_timestamp())
