from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres@127.0.0.1:5433/finanzplaner"
    test_database_url: str = "postgresql+psycopg://postgres@127.0.0.1:5433/finanzplaner_test"
    cors_origins: list[str] = ["http://localhost:5173"]
    timezone: str = "Europe/Berlin"
    # Wanddisplay (GET /wall, ohne Profil): nur Anfragen aus diesen Netzen
    wall_allowed_networks: list[str] = [
        "127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7", "fe80::/10",
    ]
    # Import: inbox/<watch-ordner>/, processing/, archive/, failed/
    import_dir: Path = Path("imports")
    max_upload_mb: int = 10
    worker_poll_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
