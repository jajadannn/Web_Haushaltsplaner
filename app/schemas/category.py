from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import CategoryType
from app.schemas.common import Name, PatchModel, ReadModel

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Icon = Annotated[str, Field(max_length=50)]


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    type: CategoryType
    parent_id: int | None = None
    icon: Icon | None = None
    color: Color | None = None


class CategoryUpdate(PatchModel):
    _not_nullable = frozenset({"name", "type", "active"})
    name: Name | None = None
    type: CategoryType | None = None
    parent_id: int | None = None
    icon: Icon | None = None
    color: Color | None = None
    active: bool | None = None


class CategoryMerge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: int


class CategoryRead(ReadModel):
    id: int
    name: str
    type: CategoryType
    parent_id: int | None
    icon: str | None
    color: str | None
    active: bool
    system_key: str | None
    created_at: datetime
