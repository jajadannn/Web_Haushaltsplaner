from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import created_at_column


class Institution(SQLModel, table=True):
    """Bank bzw. Kreditgeber; gruppiert Konten und (ab E4) Importprofile."""

    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        UniqueConstraint("id", "user_id"),  # Ziel für zusammengesetzte FKs
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id")
    name: str = Field(max_length=100)
    bic: str | None = Field(default=None, max_length=11)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
