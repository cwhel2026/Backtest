"""Build multi-timeframe candles from market events; only emit completed bars."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.bars import Bar, TIMEFRAME_MINUTES
from app.models.live_lab import LiveCompletedCandle, LiveIncompleteCandle
from app.services.live_lab.types import EventKind, MarketEvent
from app.services.market_data.streaming_aggregate import StreamingAggregator


def _bar_from_event(ev: MarketEvent) -> Bar | None:
    p = ev.payload or {}
    if ev.kind == EventKind.CANDLE_CLOSE and all(k in p for k in ("open", "high", "low", "close")):
        return Bar(
            ts=ev.exchange_ts.astimezone(UTC),
            open=Decimal(str(p["open"])),
            high=Decimal(str(p["high"])),
            low=Decimal(str(p["low"])),
            close=Decimal(str(p["close"])),
            volume=int(p.get("volume") or ev.size or 0),
        )
    if ev.kind == EventKind.TRADE and ev.price is not None:
        px = ev.price
        return Bar(ts=ev.exchange_ts.astimezone(UTC), open=px, high=px, low=px, close=px, volume=ev.size or 1)
    return None


def _load_aggregator_state(session: Session, symbol: str, tf: str) -> tuple[StreamingAggregator | None, dict]:
    row = session.execute(
        select(LiveIncompleteCandle).where(
            LiveIncompleteCandle.symbol == symbol, LiveIncompleteCandle.timeframe == tf
        )
    ).scalar_one_or_none()
    if not row or not row.state:
        return StreamingAggregator(tf), {}
    st = row.state
    agg = StreamingAggregator(tf)
    if st.get("bucket_key"):
        agg._bucket_key = datetime.fromisoformat(st["bucket_key"])
    if st.get("bars"):
        agg._bucket = [
            Bar(
                ts=datetime.fromisoformat(b["ts"]),
                open=Decimal(b["open"]),
                high=Decimal(b["high"]),
                low=Decimal(b["low"]),
                close=Decimal(b["close"]),
                volume=int(b["volume"]),
            )
            for b in st["bars"]
        ]
    return agg, st


def _save_aggregator_state(session: Session, symbol: str, tf: str, agg: StreamingAggregator) -> None:
    row = session.execute(
        select(LiveIncompleteCandle).where(
            LiveIncompleteCandle.symbol == symbol, LiveIncompleteCandle.timeframe == tf
        )
    ).scalar_one_or_none()
    state = {
        "bucket_key": agg._bucket_key.isoformat() if agg._bucket_key else None,
        "bars": [
            {
                "ts": b.ts.isoformat(),
                "open": str(b.open),
                "high": str(b.high),
                "low": str(b.low),
                "close": str(b.close),
                "volume": b.volume,
            }
            for b in agg._bucket
        ],
    }
    if row is None:
        row = LiveIncompleteCandle(symbol=symbol, timeframe=tf, bucket_ts=agg._bucket_key, state=state)
        session.add(row)
    else:
        row.bucket_ts = agg._bucket_key
        row.state = state
        row.updated_at = datetime.now(UTC)


def _persist_completed(
    session: Session,
    symbol: str,
    tf: str,
    bar: Bar,
    *,
    source: str,
    exchange_ts: datetime,
    server_ts: datetime,
) -> LiveCompletedCandle | None:
    existing = session.execute(
        select(LiveCompletedCandle).where(
            LiveCompletedCandle.symbol == symbol,
            LiveCompletedCandle.timeframe == tf,
            LiveCompletedCandle.ts == bar.ts,
        )
    ).scalar_one_or_none()
    if existing:
        return None
    row = LiveCompletedCandle(
        symbol=symbol,
        timeframe=tf,
        ts=bar.ts,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=source,
        exchange_event_ts=exchange_ts,
        server_received_ts=server_ts,
    )
    session.add(row)
    return row


TARGET_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")


def ingest_market_events(session: Session, events: list[MarketEvent]) -> list[LiveCompletedCandle]:
    """Return newly completed candles across configured timeframes."""
    completed: list[LiveCompletedCandle] = []
    for ev in sorted(events, key=lambda e: (e.exchange_ts, e.sequence)):
        bar_1m = _bar_from_event(ev)
        if bar_1m is None:
            continue
        sym = ev.symbol.upper()
        if ev.kind == EventKind.CANDLE_CLOSE and (ev.payload or {}).get("timeframe") == "1m":
            row = _persist_completed(
                session,
                sym,
                "1m",
                bar_1m,
                source=ev.source,
                exchange_ts=ev.exchange_ts,
                server_ts=ev.server_received_ts,
            )
            if row:
                completed.append(row)
        else:
            agg1 = StreamingAggregator("1m")
            done_1m = agg1.ingest_1m(bar_1m)
            agg1.flush()
            for b in done_1m:
                row = _persist_completed(
                    session,
                    sym,
                    "1m",
                    b,
                    source=ev.source,
                    exchange_ts=ev.exchange_ts,
                    server_ts=ev.server_received_ts,
                )
                if row:
                    completed.append(row)
            if not done_1m:
                row = _persist_completed(
                    session,
                    sym,
                    "1m",
                    bar_1m,
                    source=ev.source,
                    exchange_ts=ev.exchange_ts,
                    server_ts=ev.server_received_ts,
                )
                if row:
                    completed.append(row)
        for tf in TARGET_TIMEFRAMES:
            if tf == "1m":
                continue
            agg_tf, _ = _load_aggregator_state(session, sym, tf)
            if agg_tf is None:
                agg_tf = StreamingAggregator(tf)
            done_tf = agg_tf.ingest_1m(bar_1m)
            for b in done_tf:
                row = _persist_completed(
                    session,
                    sym,
                    tf,
                    b,
                    source=ev.source,
                    exchange_ts=ev.exchange_ts,
                    server_ts=ev.server_received_ts,
                )
                if row:
                    completed.append(row)
            _save_aggregator_state(session, sym, tf, agg_tf)
    return completed


def load_closed_bars(session: Session, symbol: str, timeframe: str, limit: int = 500) -> list[Bar]:
    rows = (
        session.execute(
            select(LiveCompletedCandle)
            .where(LiveCompletedCandle.symbol == symbol, LiveCompletedCandle.timeframe == timeframe)
            .order_by(LiveCompletedCandle.ts.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    rows.reverse()
    return [
        Bar(ts=r.ts, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume) for r in rows
    ]