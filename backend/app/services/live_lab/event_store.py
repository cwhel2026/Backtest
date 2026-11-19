"""Durable market-event archive with idempotent inserts and replay."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.live_lab import LiveMarketEvent
from app.services.live_lab.types import MarketEvent


def persist_events(session: Session, events: list[MarketEvent], *, provider: str) -> int:
    from app.services.live_lab.certification.integrity import quality_gate_ok, validate_event

    inserted = 0
    last_ts = None
    last_seq = None
    issues: list[str] = []
    for ev in sorted(events, key=lambda e: (e.exchange_ts, e.sequence)):
        issues.extend(validate_event(ev, last_exchange_ts=last_ts, last_sequence=last_seq))
        if not quality_gate_ok(issues):
            raise ValueError(f"Market data quality gate: {issues[-1]}")
        last_ts = ev.exchange_ts
        last_seq = ev.sequence
        key = ev.idempotency_key
        exists = session.execute(
            select(LiveMarketEvent.id).where(LiveMarketEvent.idempotency_key == key)
        ).scalar_one_or_none()
        if exists:
            continue
        row = LiveMarketEvent(
            id=uuid4(),
            provider=provider,
            symbol=ev.symbol.upper(),
            kind=ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind),
            exchange_ts=ev.exchange_ts,
            server_received_ts=ev.server_received_ts,
            latency_mode=ev.latency_mode,
            sequence=ev.sequence,
            idempotency_key=key,
            payload={
                "price": str(ev.price) if ev.price is not None else None,
                "bid": str(ev.bid) if ev.bid is not None else None,
                "ask": str(ev.ask) if ev.ask is not None else None,
                "size": ev.size,
                **ev.payload,
            },
        )
        session.add(row)
        inserted += 1
    return inserted


def replay_events_from_store(session: Session, *, after_ts: datetime | None = None, limit: int = 5000) -> list[MarketEvent]:
    from app.services.live_lab.types import EventKind, MarketEvent

    q = select(LiveMarketEvent).order_by(LiveMarketEvent.exchange_ts, LiveMarketEvent.sequence)
    if after_ts:
        q = q.where(LiveMarketEvent.exchange_ts > after_ts)
    rows = session.execute(q.limit(limit)).scalars().all()
    out: list[MarketEvent] = []
    for r in rows:
        p = r.payload or {}
        out.append(
            MarketEvent(
                symbol=r.symbol,
                kind=EventKind(r.kind),
                exchange_ts=r.exchange_ts,
                server_received_ts=r.server_received_ts,
                latency_mode=r.latency_mode,
                source="event_store",
                price=Decimal(str(p["price"])) if p.get("price") else None,
                bid=Decimal(str(p["bid"])) if p.get("bid") else None,
                ask=Decimal(str(p["ask"])) if p.get("ask") else None,
                size=p.get("size"),
                sequence=r.sequence,
                payload=p,
            )
        )
    return out