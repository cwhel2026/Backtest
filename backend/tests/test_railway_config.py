import os

from app.core.config import Settings


def test_postgres_url_normalized_for_asyncpg():
    s = Settings(database_url="postgres://user:pass@host:5432/railway")
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.database_url_sync.startswith("postgresql://")


def test_railway_celery_uses_redis_url(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    s = Settings(
        redis_url="redis://default:secret@redis.railway.internal:6379",
        celery_broker_url="redis://localhost:6379/1",
        celery_result_backend="redis://localhost:6379/2",
    )
    assert "redis.railway.internal" in s.celery_broker_url
    assert s.celery_broker_url == s.celery_result_backend