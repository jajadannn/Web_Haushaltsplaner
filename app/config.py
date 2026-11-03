from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres@127.0.0.1:5433/finanzplaner"
    test_database_url: str = "postgresql+psycopg://postgres@127.0.0.1:5433/finanzplaner_test"
    cors_origins: list[str] = ["http://localhost:5173"]
    timezone: str = "Europe/Berlin"
    # Heimnetz-Betrieb ohne Passwort: API und Oberfläche antworten nur Anfragen aus diesen Netzen
    # (Loopback und private Netze). Früherer Name: WALL_ALLOWED_NETWORKS.
    allowed_networks: list[str] = Field(
        default=["127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7", "fe80::/10"],
        validation_alias=AliasChoices("allowed_networks", "wall_allowed_networks"),
    )
    # Import: inbox/<watch-ordner>/, processing/, archive/, failed/
    import_dir: Path = Path("imports")
    max_upload_mb: int = 10
    worker_poll_seconds: float = 2.0
    # Lokale KI für die Prüfliste. Ohne Adresse ist sie aus.
    # Ollama:                     AI_URL=http://192.168.1.50:11434
    # OpenAI-kompatibel (LM Studio, llama.cpp, vLLM): AI_URL=http://192.168.1.50:1234/v1
    ai_url: str | None = Field(default=None, validation_alias=AliasChoices("ai_url", "ollama_url"))
    ai_model: str = "gemma4:e2b"
    ai_timeout_seconds: float = 300.0
    # Gleichzeitige Anfragen an den KI-Server (1–4); mehr bremst kleine Server eher aus
    ai_parallel: int = Field(default=4, ge=1, le=4)

    @property
    def ai_api(self) -> str:
        """„openai“ für Adressen auf …/v1 (OpenAI-kompatibel), sonst „ollama“."""
        return "openai" if self.ai_url and self.ai_url.rstrip("/").endswith("/v1") else "ollama"


@lru_cache
def get_settings() -> Settings:
    return Settings()
