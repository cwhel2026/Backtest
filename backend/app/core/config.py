import os
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.railway import celery_urls_from_redis, to_async_database_url, to_sync_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PROP EDGE AI"
    environment: str = "development"
    log_level: str = "INFO"
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 24

    # Railway injects DATABASE_URL / REDIS_URL; local docker-compose uses these names too.
    database_url: str = Field(
        default="postgresql+asyncpg://propedge:propedge_dev@localhost:5432/propedge",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    database_url_sync: str = Field(
        default="postgresql://propedge:propedge_dev@localhost:5432/propedge",
        validation_alias=AliasChoices("DATABASE_URL_SYNC", "database_url_sync"),
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("REDIS_URL", "redis_url"),
    )
    celery_broker_url: str = Field(
        default="redis://localhost:6379/1",
        validation_alias=AliasChoices("CELERY_BROKER_URL", "celery_broker_url"),
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2",
        validation_alias=AliasChoices("CELERY_RESULT_BACKEND", "celery_result_backend"),
    )

    port: int = Field(default=8000, validation_alias="PORT")

    allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias="ALLOWED_ORIGINS",
    )

    initial_admin_email: str = Field(
        default="admin@propedge.local",
        validation_alias=AliasChoices("INITIAL_ADMIN_EMAIL", "initial_admin_email", "ADMIN_EMAIL"),
    )
    initial_admin_password: str = Field(
        default="PropEdge!ChangeMe123",
        validation_alias=AliasChoices(
            "INITIAL_ADMIN_PASSWORD",
            "initial_admin_password",
            "ADMIN_PASSWORD",
            "PASSWORD",
        ),
    )

    databento_api_key: str = ""
    finzdata_api_key: str = Field(default="", validation_alias=AliasChoices("FINZDATA_API_KEY", "finzdata_api_key"))
    ibkr_host: str = Field(default="", validation_alias=AliasChoices("IBKR_HOST", "ibkr_host"))
    ibkr_port: int = Field(default=7497, validation_alias=AliasChoices("IBKR_PORT", "ibkr_port"))
    ibkr_client_id: int = Field(default=11, validation_alias=AliasChoices("IBKR_CLIENT_ID", "ibkr_client_id"))
    openai_api_key: str = ""
    openai_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("OPENAI_MODEL", "openai_model"))
    ai_research_enabled: bool = False
    max_experiments_per_day: int = 50
    autonomous_hourly_enabled: bool = Field(default=True, validation_alias="AUTONOMOUS_HOURLY_ENABLED")
    autonomous_forward_sim: bool = True
    search_budget_per_symbol: int = Field(default=150, validation_alias="SEARCH_BUDGET_PER_SYMBOL")
    search_history_days: int = Field(default=50, validation_alias="SEARCH_HISTORY_DAYS")
    search_symbols: str = Field(default="MNQ,NQ,MES,ES", validation_alias="SEARCH_SYMBOLS")
    search_stale_queued_minutes: int = Field(default=12, validation_alias="SEARCH_STALE_QUEUED_MINUTES")
    search_stale_running_minutes: int = Field(default=25, validation_alias="SEARCH_STALE_RUNNING_MINUTES")
    search_backtest_timeout_s: int = Field(default=90, validation_alias="SEARCH_BACKTEST_TIMEOUT_S")
    reverse_search_enabled: bool = Field(default=True, validation_alias="REVERSE_SEARCH_ENABLED")
    reverse_winrate_max: float = Field(default=0.20, validation_alias="REVERSE_WINRATE_MAX")
    search_walkforward_folds: int = Field(default=3, validation_alias="SEARCH_WALKFORWARD_FOLDS")
    search_oos_min_win_rate: float = Field(default=0.38, validation_alias="SEARCH_OOS_MIN_WIN_RATE")
    search_ai_rounds: int = Field(default=2, validation_alias="SEARCH_AI_ROUNDS")
    search_ai_specs_per_round: int = Field(default=14, validation_alias="SEARCH_AI_SPECS_PER_ROUND")
    search_timeframes: str = Field(default="5m,1m", validation_alias="SEARCH_TIMEFRAMES")
    search_1m_budget_per_symbol: int = Field(default=72, validation_alias="SEARCH_1M_BUDGET_PER_SYMBOL")
    search_1m_history_days: int = Field(default=7, validation_alias="SEARCH_1M_HISTORY_DAYS")
    search_prefer_ibkr: bool = Field(default=False, validation_alias="SEARCH_PREFER_IBKR")
    search_robustness_enabled: bool = Field(default=True, validation_alias="SEARCH_ROBUSTNESS_ENABLED")
    search_robustness_shuffles: int = Field(default=8, validation_alias="SEARCH_ROBUSTNESS_SHUFFLES")
    search_stress_slip_ticks: int = Field(default=2, validation_alias="SEARCH_STRESS_SLIP_TICKS")
    search_robustness_min_pass: float = Field(default=0.5, validation_alias="SEARCH_ROBUSTNESS_MIN_PASS")
    paper_starting_equity: float = Field(default=100_000, validation_alias="PAPER_STARTING_EQUITY")
    paper_daily_loss: float = Field(default=2_000, validation_alias="PAPER_DAILY_LOSS")
    paper_trailing_dd: float = Field(default=3_000, validation_alias="PAPER_TRAILING_DD")
    paper_profit_target: float = Field(default=6_000, validation_alias="PAPER_PROFIT_TARGET")
    paper_max_slots: int = Field(default=8, validation_alias="PAPER_MAX_SLOTS")

    api_v1_prefix: str = "/api/v1"

    @field_validator(
        "database_url",
        "database_url_sync",
        "initial_admin_email",
        "initial_admin_password",
        mode="before",
    )
    @classmethod
    def _strip_wrapping_quotes(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().strip('"').strip("'")
        return v

    @field_validator(
        "search_budget_per_symbol",
        "search_history_days",
        "search_stale_queued_minutes",
        "search_stale_running_minutes",
        "search_backtest_timeout_s",
        "search_walkforward_folds",
        "search_ai_rounds",
        "search_ai_specs_per_round",
        "search_1m_budget_per_symbol",
        "search_1m_history_days",
        "search_robustness_shuffles",
        "search_stress_slip_ticks",
        mode="before",
    )
    @classmethod
    def _coerce_env_int(cls, v: object) -> object:
        """Railway env values are sometimes set as \"60+\" — strip trailing plus signs."""
        if isinstance(v, str):
            s = v.strip().strip('"').strip("'")
            while s.endswith("+"):
                s = s[:-1].strip()
            if s.isdigit():
                return int(s)
        return v

    @model_validator(mode="after")
    def _railway_compatibility(self) -> "Settings":
        self.database_url = to_async_database_url(self.database_url)
        if self.database_url_sync.startswith("postgresql+asyncpg"):
            self.database_url_sync = to_sync_database_url(self.database_url_sync)
        elif self.database_url_sync in (
            "",
            "postgresql://propedge:propedge_dev@localhost:5432/propedge",
        ) or self.database_url_sync == self.database_url:
            self.database_url_sync = to_sync_database_url(self.database_url)

        on_railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))
        if on_railway and self.redis_url:
            broker, backend = celery_urls_from_redis(self.redis_url)
            self.celery_broker_url = broker
            self.celery_result_backend = backend
        return self

    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def databento_configured(self) -> bool:
        return bool(self.databento_api_key.strip())

    @property
    def finzdata_configured(self) -> bool:
        return bool(self.finzdata_api_key.strip())

    @property
    def ai_configured(self) -> bool:
        return bool(self.openai_api_key.strip()) and self.ai_research_enabled

    @property
    def ibkr_configured(self) -> bool:
        return bool(self.ibkr_host.strip())

    def search_timeframe_list(self) -> list[str]:
        return [t.strip() for t in self.search_timeframes.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()