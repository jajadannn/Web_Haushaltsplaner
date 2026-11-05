from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import MatchField, MatchType
from app.schemas.common import Money, Name, PatchModel, ReadModel
from app.schemas.transaction import TransactionRead

Pattern = Annotated[str, Field(min_length=2, max_length=200)]
Priority = Annotated[int, Field(ge=0, le=10000)]


class RuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    pattern: Pattern
    match_type: MatchType = MatchType.CONTAINS
    match_field: MatchField = MatchField.ANY
    case_sensitive: bool = False
    priority: Priority = 100
    target_category_id: int
    active: bool = True


class RuleUpdate(PatchModel):
    _not_nullable = frozenset({"pattern", "match_type", "match_field", "case_sensitive", "priority",
                               "target_category_id", "active"})
    name: Name | None = None
    pattern: Pattern | None = None
    match_type: MatchType | None = None
    match_field: MatchField | None = None
    case_sensitive: bool | None = None
    priority: Priority | None = None
    target_category_id: int | None = None
    active: bool | None = None


class RuleRead(ReadModel):
    id: int
    name: str | None
    pattern: str
    match_type: MatchType
    match_field: MatchField
    case_sensitive: bool
    priority: int
    target_category_id: int
    active: bool
    created_at: datetime
    updated_at: datetime


class RulePreviewRequest(BaseModel):
    """Text testen oder eine vorhandene Buchung (`transaction_id`)."""

    model_config = ConfigDict(extra="forbid")
    description: Annotated[str, Field(max_length=1000)] | None = None
    counterparty: Annotated[str, Field(max_length=200)] | None = None
    transaction_id: int | None = None


class RulePreview(BaseModel):
    matching: list[RuleRead]
    winner: RuleRead | None


class ApplySample(BaseModel):
    transaction_id: int
    booking_date: date
    description: str
    old_category_id: int | None
    new_category_id: int
    rule_id: int


class ApplyResult(BaseModel):
    dry_run: bool
    affected: int
    sample: list[ApplySample]


class LoanSuggestion(BaseModel):
    loan_id: int
    loan_name: str
    seq: int
    due_date: date
    planned_installment: str


class ReviewItem(BaseModel):
    transaction: TransactionRead
    suggested_loan: LoanSuggestion | None = None
    priority_reason: str | None = None  # nur bei order=priority: warum die Buchung so weit oben steht


class ReviewGroup(BaseModel):
    """Ähnliche offene Buchungen (gleiche Gegenpartei, gleiche Richtung) zum gemeinsamen Prüfen."""

    key: str
    label: str
    direction: Literal["in", "out"]
    count: int
    total: Money
    transaction_ids: list[int]
    category_ids: list[int]  # bereits vorgeschlagene Kategorien (z. B. per Regel/KI)


class ReviewPage(BaseModel):
    items: list[ReviewItem]
    total: int
    limit: int
    offset: int


class ReviewConfirm(BaseModel):
    """Ohne Angaben wird die vorhandene (z. B. per Regel gesetzte) Kategorie bestätigt."""

    model_config = ConfigDict(extra="forbid")
    category_id: int | None = None
    as_transfer: bool = False


class BulkConfirm(ReviewConfirm):
    transaction_ids: Annotated[list[int], Field(min_length=1, max_length=500)]


class RuleSuggestion(BaseModel):
    name: str
    pattern: str
    match_type: MatchType
    match_field: MatchField
    target_category_id: int | None
    matching_transactions: int


class AiEndpointStatus(BaseModel):
    priority: int  # 1 = zuerst gefragt, 2 = übernimmt bei Ausfall
    url: str
    model: str
    vision_model: str
    reachable: bool


class AiStatus(BaseModel):
    """Lokale KI in der Prüfliste."""

    enabled: bool  # AI_URL gesetzt
    model: str | None  # Modell von Priorität 1
    reachable: bool | None  # mindestens ein Server erreichbar; None, wenn aus
    pending: int  # Buchungen dieses Profils, die die KI noch prüfen wird
    endpoints: list[AiEndpointStatus] = []  # alle eingerichteten Server in Prioritätsreihenfolge


class AiRetryResult(BaseModel):
    queued: int


class ConfirmAllResult(BaseModel):
    confirmed: int
    skipped: int  # ließen sich nicht bestätigen und bleiben in der Liste
