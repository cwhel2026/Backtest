"""Aggregate platform health for dashboard — feed, workers, DB, research cadence."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.models.enums import ResearchJobStatus
from app.models.live_lab import LiveCompletedCandle, LiveFeedStatus
from app.models.research import ResearchJob
from app.models.scanner import ScannerSetup, WorkerHealthBeat
from app.services.cme_market_clock import cme_futures_market_status
from app.services.market_data.storage_backend import resolved_store_path
from app.services.worker_health import worker_is_stale


def build_platform_status(session: Session) -> dict:
    now = datetime.now(UTC)
    feed = session.execute(select(LiveFeedStatus).order_by(LiveFeedStatus.updated_at.desc()).limit(1)).scalar_one_or_none()
    beats = session.execute(select(WorkerHealthBeat)).scalars().all()
    beat_out = []
    for b in beats:
        beat_out.append(
            {
                "worker_name": b.worker_name,
                "last_success_at": b.last_success_at.isoformat() if b.last_success_at else None,
                "last_attempt_at": b.last_attempt_at.isoformat(),
                "stale": worker_is_stale(b, now=now),
                "stale_after_seconds": b.stale_after_seconds,
                "detail": b.detail or {},
            }
        )

    db_ok = False
    try:
        session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        db_ok = False
        db_err = str(exc)
    else:
        db_err = None

    redis_ok = False
    redis_err = None
    try:
        from app.core.config import get_settings
        import redis

        settings = get_settings()
        r = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        redis_ok = True
    except Exception as exc:
        redis_err = str(exc)[:200]

    last_research = session.execute(
        select(ResearchJob).order_by(desc(ResearchJob.completed_at)).where(ResearchJob.status == ResearchJobStatus.COMPLETED).limit(1)
    ).scalar_one_or_none()
    last_scanner = session.execute(select(ScannerSetup).order_by(desc(ScannerSetup.detected_at)).limit(1)).scalar_one_or_none()

    worker_stale = any(worker_is_stale(b, now=now) for b in beats) if beats else True

    feed_active = bool(
        feed
        and feed.connection_status.value == "connected"
        and not feed.is_paused
        and not worker_stale
    )

    markets: list[dict] = []
    if feed:
        symbols = {s for (s,) in session.execute(select(LiveCompletedCandle.symbol).distinct()).all()}
        for sym in sorted(symbols):
            latest = session.execute(
                select(LiveCompletedCandle)
                .where(LiveCompletedCandle.symbol == sym, LiveCompletedCandle.timeframe == "5m")
                .order_by(LiveCompletedCandle.ts.desc())
                .limit(1)
            ).scalar_one_or_none()
            age_sec = None
            if latest:
                age_sec = (now - latest.ts).total_seconds()
            markets.append(
                {
                    "symbol": sym,
                    "last_candle_ts": latest.ts.isoformat() if latest else None,
                    "last_close": float(latest.close) if latest else None,
                    "data_age_seconds": age_sec,
                    "source": latest.source if latest else None,
                }
            )

    store = resolved_store_path()
    return {
        "generated_at": now.isoformat(),
        "cme_session": cme_futures_market_status(now=now),
        "storage": {
            "ohlcv_root": str(store.resolve()),
            "volume_mounted": __import__("pathlib").Path("/data").is_dir(),
        },
        "market_data": {
            "provider": feed.provider if feed else None,
            "latency_mode": feed.latency_mode.value if feed and feed.latency_mode else "synthetic",
            "connection_status": feed.connection_status.value if feed else "disconnected",
            "is_paused": feed.is_paused if feed else True,
            "last_heartbeat_at": feed.last_heartbeat_at.isoformat() if feed and feed.last_heartbeat_at else None,
            "last_event_exchange_ts": feed.last_event_exchange_ts.isoformat() if feed and feed.last_event_exchange_ts else None,
            "platform_active": feed_active,
        },
        "workers": beat_out,
        "database": {"ok": db_ok, "error": db_err},
        "redis": {"ok": redis_ok, "error": redis_err},
        "scheduler": {
            "last_research_completed_at": last_research.completed_at.isoformat() if last_research and last_research.completed_at else None,
            "last_scanner_setup_at": last_scanner.detected_at.isoformat() if last_scanner else None,
        },
        "markets": markets,
        "active_warning": None
        if feed_active
        else "Scheduled ingestion or forward processing may be stale — see worker heartbeats.",
    }