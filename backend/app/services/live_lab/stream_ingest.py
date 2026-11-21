"""Continuous market-event ingestion (separate from forward-test bar tick)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import LiveFeedConnectionStatus, MarketLatencyMode
from app.models.live_lab import LiveFeedStatus
from app.services.live_lab.candle_engine import ingest_market_events
from app.services.live_lab.event_store import persist_events, replay_events_from_store
from app.services.live_lab.market_data.registry import get_market_data_adapter
from app.services.live_lab.service import ensure_feed_status, pause_all_forward_tests


def ingest_stream_once(session: Session) -> dict:
    """Pull from adapter, persist, build candles — idempotent."""
    adapter = get_market_data_adapter(session)
    feed = ensure_feed_status(session, adapter.provider_id)
    settings = get_settings()
    used_store = False
    events = []
    try:
        if settings.live_lab_provider == "event_store":
            cursor = feed.meta.get("last_replay_ts")
            after = datetime.fromisoformat(cursor) if cursor else None
            events = replay_events_from_store(session, after_ts=after, limit=2000)
            used_store = True
            adapter_desc = {"provider": "event_store", "latency_mode": MarketLatencyMode.HISTORICAL_REPLAY.value}
        else:
            adapter.connect()
            events = adapter.poll_events(limit=500)
            adapter_desc = adapter.describe()
            adapter.disconnect()
        feed.connection_status = LiveFeedConnectionStatus.CONNECTED
        feed.is_paused = False
        feed.meta = {**(feed.meta or {}), **adapter_desc}
        mode = adapter_desc.get("latency_mode") or MarketLatencyMode.SYNTHETIC.value
        feed.latency_mode = MarketLatencyMode(mode)
    except Exception as exc:
        feed.connection_status = LiveFeedConnectionStatus.ERROR
        feed.is_paused = True
        feed.incidents = (feed.incidents or [])[-49:] + [
            {"ts": datetime.now(UTC).isoformat(), "kind": "ingest_error", "detail": str(exc)}
        ]
        pause_all_forward_tests(session, f"Stream ingest error: {exc}")
        return {"ok": False, "error": str(exc)}

    if not used_store:
        persist_events(session, events, provider=adapter.provider_id)

    now = datetime.now(UTC)
    feed.last_heartbeat_at = now
    if events:
        feed.last_event_exchange_ts = events[-1].exchange_ts
        feed.last_event_server_ts = events[-1].server_received_ts
        feed.meta["last_replay_ts"] = events[-1].exchange_ts.isoformat()

    if feed.latency_mode == MarketLatencyMode.REALTIME:
        stale = now - timedelta(seconds=feed.stale_seconds)
        if feed.last_event_server_ts and feed.last_event_server_ts < stale:
            feed.connection_status = LiveFeedConnectionStatus.STALE
            pause_all_forward_tests(session, "Stale stream feed")

    completed = ingest_market_events(session, events) if events else []
    feed.updated_at = now
    out: dict = {
        "ok": True,
        "events": len(events),
        "candles": len(completed),
        "provider": feed.provider,
        "latency_mode": feed.latency_mode.value,
        "used_event_store": used_store,
    }
    if not events:
        if settings.live_lab_provider == "replay" and not (settings.live_lab_replay_path or "").strip():
            out["idle_reason"] = "replay_provider_missing_LIVE_LAB_REPLAY_PATH"
        else:
            out["idle_reason"] = "no_market_events_this_poll"
    return out