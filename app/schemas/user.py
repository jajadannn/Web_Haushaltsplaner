from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Name, PatchModel, ReadModel


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name


class UserUpdate(PatchModel):
    _not_nullable = frozenset({"name"})
    name: Name | None = None


class UserRead(ReadModel):
    id: int
    name: str
    created_at: datetime
