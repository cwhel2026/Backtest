"""PostgreSQL integration — real services (no mocked DB). Skipped unless LIVE_LAB_INTEGRATION=1."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_LAB_INTEGRATION") != "1",
    reason="Set LIVE_LAB_INTEGRATION=1 with Postgres reachable at DATABASE_URL_SYNC",
)

REPORT: dict[str, str] = {}


def _report(step: str, status: str, detail: str = "") -> None:
    REPORT[step] = f"{status}:{detail}"[:500]


@pytest.fixture(scope="module")
def pg_session() -> Session:
    url = os.environ.get("DATABASE_URL_SYNC")
    if not url:
        pytest.fail("DATABASE_URL_SYNC required for integration tests")
    engine = create_engine(url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        yield session
    engine.dispose()


def test_integration_pass_fail_report(pg_session: Session, monkeypatch):
    """Market data → candles → scanner persistence → worker beat → idempotent re-ingest."""
    from app.models.live_lab import LiveCompletedCandle, LiveMarketEvent
    from app.models.scanner import ScannerSetup, WorkerHealthBeat
    from app.services.instruments_sync import seed_instruments_sync
    from app.services.live_lab.event_store import persist_events
    from app.services.live_lab.market_data.replay import ReplayMarketDataAdapter
    from app.core.config import get_settings
    from app.models.enums import LiveFeedConnectionStatus
    from app.services.live_lab.service import ensure_feed_status, tick_live_strategy_lab
    from app.services.live_lab.stream_ingest import ingest_stream_once
    from app.services.worker_health import record_worker_beat

    get_settings.cache_clear()

    # --- DB connectivity ---
    try:
        pg_session.execute(text("SELECT 1"))
        _report("postgres", "PASS")
    except Exception as exc:
        _report("postgres", "FAIL", str(exc))
        pytest.fail(f"Postgres: {exc}")

    # --- Redis (optional but reported) ---
    try:
        import redis

        rurl = os.environ.get("REDIS_URL") or os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.from_url(rurl, socket_connect_timeout=2)
        r.ping()
        _report("redis", "PASS")
    except Exception as exc:
        _report("redis", "FAIL", str(exc))

    seed_instruments_sync(pg_session)
    pg_session.commit()

    fixture = Path(__file__).parent / "fixtures" / "live_lab_acceptance.jsonl"
    adapter = ReplayMarketDataAdapter(path=fixture)
    events = adapter._queue  # noqa: SLF001
    assert events, "fixture events required"
    _report("fixture_load", "PASS", f"events={len(events)}")

    feed = ensure_feed_status(pg_session, "replay")
    feed.is_paused = False
    feed.connection_status = LiveFeedConnectionStatus.CONNECTED
    pg_session.commit()

    monkeypatch.setenv("LIVE_LAB_PROVIDER", "replay")
    get_settings.cache_clear()
    n1 = persist_events(pg_session, events, provider="replay")
    pg_session.commit()
    _report("event_persist", "PASS" if n1 == len(events) else "FAIL", f"written={n1}")

    # Duplicate persist must not inflate event count
    before = pg_session.scalar(select(func.count()).select_from(LiveMarketEvent))
    persist_events(pg_session, events, provider="replay")
    pg_session.commit()
    after = pg_session.scalar(select(func.count()).select_from(LiveMarketEvent))
    assert after == before, "duplicate events must be idempotent"
    _report("duplicate_events", "PASS")

    monkeypatch.setenv("LIVE_LAB_PROVIDER", "event_store")
    get_settings.cache_clear()
    ing1 = ingest_stream_once(pg_session)
    pg_session.commit()
    candles1 = ing1.get("candles", 0)
    _report("ingest_candles", "PASS" if ing1.get("ok") and candles1 else "FAIL", str(ing1))

    tick1 = tick_live_strategy_lab(pg_session)
    pg_session.commit()
    _report("forward_tick", "PASS" if tick1.get("ok") else "FAIL", str(tick1))

    setups = pg_session.scalar(select(func.count()).select_from(ScannerSetup))
    _report("scanner_setups", "PASS" if setups is not None else "FAIL", f"count={setups}")

    record_worker_beat(pg_session, "integration_test", success=True, detail={"phase": "first"})
    pg_session.commit()

    # Simulated worker restart: re-run ingest + tick
    ing2 = ingest_stream_once(pg_session)
    tick2 = tick_live_strategy_lab(pg_session)
    pg_session.commit()
    candle_rows = pg_session.scalar(
        select(func.count()).select_from(LiveCompletedCandle).where(LiveCompletedCandle.symbol == "MES")
    )
    assert candle_rows is not None
    _report("restart_tick", "PASS" if tick2.get("ok") else "FAIL", f"mes_candles={candle_rows}")

    beat = pg_session.get(WorkerHealthBeat, "live_lab_forward")
    _report("worker_heartbeat", "PASS" if beat and beat.last_success_at else "WARN", "live_lab_forward")

    print("\n=== INTEGRATION PASS/FAIL REPORT ===")
    for step, line in REPORT.items():
        status = line.split(":", 1)[0]
        print(f"{step}: {status}")
    failures = [k for k, v in REPORT.items() if v.startswith("FAIL")]
    if failures:
        pytest.fail(f"Integration failures: {failures}")