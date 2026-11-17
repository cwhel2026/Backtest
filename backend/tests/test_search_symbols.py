from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.models.enums import ResearchJobStatus
from app.services.autonomous_cycle import job_is_stale, resolve_search_symbols


def test_running_search_without_heartbeat_is_stale():
    started = datetime.now(UTC) - timedelta(minutes=10)
    job = SimpleNamespace(
        status=ResearchJobStatus.RUNNING,
        created_at=started,
        started_at=started,
        payload={},
    )
    assert job_is_stale(job)


def test_fresh_heartbeat_is_not_stale():
    now = datetime.now(UTC)
    job = SimpleNamespace(
        status=ResearchJobStatus.RUNNING,
        created_at=now - timedelta(minutes=30),
        started_at=now - timedelta(minutes=30),
        payload={"heartbeat": now.isoformat()},
    )
    assert not job_is_stale(job, now)


def test_nasdaq_always_included(monkeypatch):
    monkeypatch.setenv("SEARCH_SYMBOLS", "MES,ES")
    # Clear settings cache if needed
    from app.core.config import get_settings

    get_settings.cache_clear()
    syms = resolve_search_symbols()
    assert "MNQ" in syms
    assert "NQ" in syms
    get_settings.cache_clear()