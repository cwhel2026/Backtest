import os

from app.core.config import Settings, get_settings


def test_postgres_url_normalized_for_asyncpg():
    s = Settings(database_url="postgres://user:pass@host:5432/railway")
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.database_url_sync.startswith("postgresql://")


def test_search_1m_window_uses_paid_days_when_finzdata_configured(monkeypatch):
    monkeypatch.setenv("FINZDATA_API_KEY", "k")
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    s = Settings(search_1m_history_days=7, search_1m_paid_history_days=30)
    assert s.search_1m_window_days() == 30
    monkeypatch.setenv("FINZDATA_API_KEY", "")
    yahoo_only = Settings(search_1m_history_days=7)
    assert yahoo_only.search_1m_window_days() == 7


def test_search_history_days_accepts_trailing_plus(monkeypatch):
    monkeypatch.setenv("SEARCH_HISTORY_DAYS", "60+")
    get_settings.cache_clear()
    s = get_settings()
    assert s.search_history_days == 60
    get_settings.cache_clear()


def test_railway_celery_uses_redis_url(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("REDIS_URL", "redis://default:secret@redis.railway.internal:6379")
    s = Settings(
        redis_url="redis://default:secret@redis.railway.internal:6379",
        celery_broker_url="redis://localhost:6379/1",
        celery_result_backend="redis://localhost:6379/2",
    )
    assert "redis.railway.internal" in s.celery_broker_url
    assert s.celery_broker_url == s.celery_result_backend