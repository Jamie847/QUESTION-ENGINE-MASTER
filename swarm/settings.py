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
    # Operator decision (WO-005): off by default. Any other value turns
    # the token gate back on. ALLOW_UNAUTHENTICATED is only read then.
    dashboard_auth: str = "off"
    allow_unauthenticated: bool = False
    max_runs_per_day: int = 5
    run_cooldown_seconds: int = 600
    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""
    anthropic_model: str = "claude-sonnet-5"
    judgment_model: str = "claude-fable-5"
    fallback_model: str = Field(
        default="",
        validation_alias=AliasChoices("FALLBACK_MODEL"),
    )
    git_commit: str = Field(
        default="",
        validation_alias=AliasChoices("RENDER_GIT_COMMIT", "GIT_COMMIT"),
    )
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
    stale_after_days: int = 3
    dedup_threshold: float = 0.64
    user_agent: str = (
        "QuestionEngine/1.0 (personal research digest; +https://render.com)"
    )
    reddit_user_agent: str = (
        "python:question-engine:1.0 (by /u/QuestionEngine; personal research digest)"
    )
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    source_dead_after_runs: int = 3
    display_tz: str = "UTC"
    allow_demo_signals: bool = False
    snippet_chars: int = 800
    scout_signals_per_vertical: int = 30
    smith_briefs_per_lens: int = 30
    smith_intersections_per_lens: int = 12
    brave_min_interval_s: float = 1.1
    openalex_api_key: str = ""
    regulations_gov_api_key: str = ""
    sam_gov_api_key: str = ""
    eia_api_key: str = ""
    fred_api_key: str = ""
    opportunity_max: int = 5
    assays_per_day: int = 10
    desk_reserve_usd: float = 0.40
    desk_cost_estimate_usd: float = 0.31

    @computed_field  # type: ignore[prop-decorator]
    @property
    def auth_token(self) -> str:
        return self.dashboard_token or self.access_token

    @property
    def dashboard_auth_enabled(self) -> bool:
        return self.dashboard_auth.strip().lower() not in {"", "off"}

    @property
    def budget_usd(self) -> float:
        return self.run_budget_usd

    @property
    def short_commit(self) -> str:
        sha = (self.git_commit or "").strip()
        return sha[:7] if sha else ""

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
