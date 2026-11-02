from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlmodel import Session

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
