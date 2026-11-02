from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Name, PatchModel, ReadModel

Bic = Annotated[str, Field(pattern=r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")]


class InstitutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    bic: Bic | None = None


class InstitutionUpdate(PatchModel):
    _not_nullable = frozenset({"name"})
    name: Name | None = None
    bic: Bic | None = None


class InstitutionRead(ReadModel):
    id: int
    name: str
    bic: str | None
    created_at: datetime
