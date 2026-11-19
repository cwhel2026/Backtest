"""Market event integrity checks on ingest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.live_lab.types import MarketEvent


def validate_event(ev: MarketEvent, *, last_exchange_ts: datetime | None, last_sequence: int | None) -> list[str]:
    issues: list[str] = []
    now = datetime.now(UTC)
    if ev.server_received_ts < ev.exchange_ts:
        issues.append("receive_before_exchange")
    if ev.server_received_ts - ev.exchange_ts > timedelta(minutes=30):
        issues.append("stale_latency")
    if last_exchange_ts and ev.exchange_ts < last_exchange_ts:
        issues.append("out_of_order_exchange_ts")
    if last_sequence is not None and ev.sequence <= last_sequence:
        issues.append("duplicate_or_regressed_sequence")
    if ev.price is not None and ev.price <= 0:
        issues.append("invalid_price")
    if not ev.latency_mode:
        issues.append("missing_latency_mode")
    return issues


def quality_gate_ok(recent_issues: list[str], *, max_issues: int = 3) -> bool:
    return len(recent_issues) <= max_issues