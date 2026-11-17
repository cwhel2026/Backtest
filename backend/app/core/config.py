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
    openai_api_key: str = ""
    openai_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("OPENAI_MODEL", "openai_model"))
    ai_research_enabled: bool = False
    max_experiments_per_day: int = 50
    autonomous_hourly_enabled: bool = Field(default=True, validation_alias="AUTONOMOUS_HOURLY_ENABLED")
    autonomous_forward_sim: bool = True

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
    def ai_configured(self) -> bool:
        return bool(self.openai_api_key.strip()) and self.ai_research_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()