from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./question_engine.db"
    dashboard_token: str = ""
    access_token: str = ""
    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""
    anthropic_model: str = "claude-sonnet-5"
    judgment_model: str = "claude-fable-5"
    brave_api_key: str = ""
    perplexity_api_key: str = ""
    run_budget_usd: float = Field(
        default=5.0,
        validation_alias=AliasChoices("RUN_BUDGET_USD", "DAILY_BUDGET_USD"),
    )
    run_token_cap: int = 400_000
    port: int = 43417
    source_timeout_s: float = Field(
        default=45.0,
        validation_alias=AliasChoices("SOURCE_TIMEOUT_SECONDS", "SOURCE_TIMEOUT_S"),
    )
    lock_stale_after_s: int = 7200
    dedup_lookback_days: int = 45
    dedup_threshold: float = 0.64
    user_agent: str = (
        "QuestionEngine/1.0 (personal research digest; +https://render.com)"
    )
    reddit_user_agent: str = (
        "python:question-engine:1.0 (by /u/QuestionEngine; personal research digest)"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def auth_token(self) -> str:
        return self.dashboard_token or self.access_token

    @property
    def budget_usd(self) -> float:
        return self.run_budget_usd

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
