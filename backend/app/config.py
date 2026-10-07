from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SB_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/silobreaker"
    # Only fixtures/input is ever read at runtime. fixtures/oracle is for tests/evaluation.
    fixtures_input_dir: Path = REPO_ROOT / "fixtures" / "input"
    # "offline" uses the deterministic rule-based extractor; "openai" calls a real model.
    ai_provider: str = "offline"
    ai_model: str = "offline-rules/1"
    openai_api_key: str | None = None
    ai_timeout_seconds: float = 60.0
    # Versions frozen into every analysis snapshot (FR-03).
    prompt_version: str = "detect/1"
    schema_version: str = "analysis/1"
    scoring_version: str = "risk/1"
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
