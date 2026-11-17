from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PROP EDGE AI"
    environment: str = "development"
    log_level: str = "INFO"
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 24

    database_url: str = "postgresql+asyncpg://propedge:propedge_dev@localhost:5432/propedge"
    database_url_sync: str = "postgresql://propedge:propedge_dev@localhost:5432/propedge"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    initial_admin_email: str = "admin@propedge.local"
    initial_admin_password: str = "PropEdge!ChangeMe123"

    databento_api_key: str = ""
    openai_api_key: str = ""
    ai_research_enabled: bool = False
    max_experiments_per_day: int = 50

    api_v1_prefix: str = "/api/v1"

    @property
    def databento_configured(self) -> bool:
        return bool(self.databento_api_key.strip())

    @property
    def ai_configured(self) -> bool:
        return bool(self.openai_api_key.strip()) and self.ai_research_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()