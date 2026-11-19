"""Derive higher timeframes from 1m parquet without loading the full series into RAM."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.backtest.bars import Bar, TIMEFRAME_MINUTES
from app.services.market_data.dataset_catalog import (
    create_pending_dataset,
    finalize_dataset_after_write,
    ingest_fingerprint,
)
from app.services.market_data.ohlcv_parquet import dataset_dir, write_bars
from app.services.market_data.streaming_aggregate import StreamingAggregator
from app.services.market_data.validate_dataset import validate_and_persist

DERIVED_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1h", "4h")
WRITE_BATCH = 2000


def _bars_from_day_parquet(path: Path) -> list[Bar]:
    import pandas as pd

    df = pd.read_parquet(path)
    if df.empty:
        return []
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    out: list[Bar] = []
    for _, row in df.iterrows():
        out.append(
            Bar(
                ts=row["ts"].to_pydatetime(),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=int(row["volume"]),
            )
        )
    return sorted(out, key=lambda b: b.ts)


def derive_timeframes_from_1m_parent(
    session: Session,
    *,
    parent: object,
    symbol: str,
    provider_slug: str = "databento",
    instrument_id: uuid.UUID,
    range_start: datetime,
    range_end: datetime,
    tick_size,
    trading_hours: dict | None,
    parent_fingerprint: str,
    timeframes: tuple[str, ...] = DERIVED_TIMEFRAMES,
    on_progress=None,
) -> list:
    from app.models.market_data import HistoricalDataset

    parent = session.get(HistoricalDataset, parent.id) if hasattr(parent, "id") else parent
    parent_id = parent.id
    parent_meta = dict(parent.meta or {})
    folder = dataset_dir(parent_id)
    day_files = sorted(folder.glob("*.parquet"))
    if not day_files:
        return []

    created = []
    for tf in timeframes:
        if tf not in TIMEFRAME_MINUTES:
            continue
        if on_progress:
            on_progress(f"Deriving {symbol} {tf}", 85)
        agg = StreamingAggregator(tf)
        fp = ingest_fingerprint(
            provider_slug=provider_slug,
            instrument_symbol=symbol,
            timeframe=tf,
            start=range_start,
            end=range_end,
        )
        child = create_pending_dataset(
            session,
            provider_slug=provider_slug,
            instrument_id=instrument_id,
            timeframe=tf,
            fingerprint=fp,
            meta={
                **{k: v for k, v in parent_meta.items() if k != "ingest_fingerprint"},
                "source": "databento_derived",
                "derived_from_dataset_id": str(parent_id),
                "derived_from_fingerprint": parent_fingerprint,
                "aggregation": "streaming_parquet_1m",
                "parent_timeframe": "1m",
                "continuous_research_only": True,
            },
        )
        session.flush()
        pending: list[tuple] = []

        def flush_tuples() -> None:
            nonlocal pending
            if pending:
                write_bars(child.id, pending)
                pending = []

        for day_path in day_files:
            for bar in _bars_from_day_parquet(day_path):
                for completed in agg.ingest_1m(bar):
                    pending.append(
                        (completed.ts, completed.open, completed.high, completed.low, completed.close, completed.volume)
                    )
                    if len(pending) >= WRITE_BATCH:
                        flush_tuples()
        for completed in agg.flush():
            pending.append(
                (completed.ts, completed.open, completed.high, completed.low, completed.close, completed.volume)
            )
        flush_tuples()
        finalize_dataset_after_write(session, child)
        validate_and_persist(
            session,
            child,
            symbol=symbol,
            tick_size=tick_size,
            instrument_trading_hours=trading_hours,
            sample_large=True,
        )
        created.append(child)
    session.flush()
    return created