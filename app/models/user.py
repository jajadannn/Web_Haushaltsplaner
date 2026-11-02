from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import created_at_column


class User(SQLModel, table=True):
    """Lokales Profil ohne Passwort (Auswahl per X-User-Id)."""

    __tablename__ = "app_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, unique=True)
    created_at: datetime | None = Field(default=None, sa_column=created_at_column())
