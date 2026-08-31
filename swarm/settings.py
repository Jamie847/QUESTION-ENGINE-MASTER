from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./question_engine.db"
    access_token: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    brave_api_key: str = ""
    perplexity_api_key: str = ""
    daily_budget_usd: float = 2.0
    port: int = 43417
    source_timeout_s: float = 12.0
    lock_stale_after_s: int = 7200
    dedup_lookback_days: int = 45
    dedup_threshold: float = 0.64
    user_agent: str = (
        "QuestionEngine/1.0 (personal research digest; +https://render.com)"
    )

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        if url.startswith("postgresql://") and "+psycopg" not in url:
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
