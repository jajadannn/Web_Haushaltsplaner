from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres@127.0.0.1:5433/finanzplaner"
    test_database_url: str = "postgresql+psycopg://postgres@127.0.0.1:5433/finanzplaner_test"
    cors_origins: list[str] = ["http://localhost:5173"]
    timezone: str = "Europe/Berlin"
    # Import: inbox/<watch-ordner>/, processing/, archive/, failed/
    import_dir: Path = Path("imports")
    max_upload_mb: int = 10
    worker_poll_seconds: float = 2.0
    stale_after_minutes: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()
