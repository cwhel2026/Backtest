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


REORDER_TOLERANCE_SEC = 2


def quality_gate_ok(recent_issues: list[str], *, max_issues: int = 3) -> bool:
    blocking = [i for i in recent_issues if i not in ("out_of_order_exchange_ts",)]
    if blocking:
        return len(blocking) <= max_issues
    return len(recent_issues) <= max_issues


def reconcile_event_batch(events: list[MarketEvent]) -> tuple[list[MarketEvent], list[str]]:
    """Sort and flag gaps; allow bounded timestamp reorder within a micro-batch."""
    warnings: list[str] = []
    ordered = sorted(events, key=lambda e: (e.exchange_ts, e.sequence or 0))
    for i in range(1, len(ordered)):
        prev, cur = ordered[i - 1], ordered[i]
        if cur.exchange_ts < prev.exchange_ts:
            delta = (prev.exchange_ts - cur.exchange_ts).total_seconds()
            if delta > REORDER_TOLERANCE_SEC:
                warnings.append("out_of_order_exchange_ts")
        if prev.sequence and cur.sequence and cur.sequence - prev.sequence > 1:
            warnings.append("sequence_gap")
    return ordered, warnings