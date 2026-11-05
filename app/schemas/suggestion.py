from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ReadModel


class SuggestionRead(ReadModel):
    id: int
    kind: str
    status: str
    fingerprint: str
    payload: dict[str, Any]
    evidence: dict[str, Any]
    reason: str
    generator: str
    priority: int
    data_as_of: datetime | None
    result_type: str | None
    result_id: int | None
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None


class RefreshResult(BaseModel):
    new: int
    updated: int
    stale: int
    by_detector: dict[str, dict[str, int]]


class ChangeRead(ReadModel):
    id: int
    object_type: str
    object_id: int
    action: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    suggestion_id: int | None
    actor: str
    reverted_at: datetime | None
    created_at: datetime
