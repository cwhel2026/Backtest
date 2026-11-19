"""Derive 5m/15m/1h/4h datasets from a validated 1m parent (deterministic aggregation)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.backtest.bars import TIMEFRAME_MINUTES, aggregate_bars, load_bars
from app.services.market_data.dataset_catalog import (
    create_pending_dataset,
    finalize_dataset_after_write,
    ingest_fingerprint,
)
from app.services.market_data.ohlcv_parquet import write_bars
from app.services.market_data.validate_dataset import validate_and_persist

DERIVED_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1h", "4h")


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
) -> list:
    """Create child datasets linked to parent 1m store."""
    from app.models.market_data import HistoricalDataset

    parent = session.get(HistoricalDataset, parent.id) if hasattr(parent, "id") else parent
    parent_id = parent.id
    bars_1m = load_bars(session, parent_id)
    if not bars_1m:
        return []

    created = []
    parent_meta = dict(parent.meta or {})
    for tf in timeframes:
        if tf not in TIMEFRAME_MINUTES:
            continue
        agg = aggregate_bars(bars_1m, tf)
        if not agg:
            continue
        tuples = [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in agg]
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
                **{k: v for k, v in parent_meta.items() if k not in ("ingest_fingerprint",)},
                "source": "databento_derived",
                "derived_from_dataset_id": str(parent_id),
                "derived_from_fingerprint": parent_fingerprint,
                "aggregation": "deterministic_from_1m",
                "parent_timeframe": "1m",
            },
        )
        write_bars(child.id, tuples)
        finalize_dataset_after_write(session, child)
        validate_and_persist(
            session,
            child,
            symbol=symbol,
            tick_size=tick_size,
            instrument_trading_hours=trading_hours,
        )
        created.append(child)
    session.flush()
    return created