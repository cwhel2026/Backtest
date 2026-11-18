"""One stored OHLCV series per symbol/timeframe.

Full history is downloaded once. Later searches and paper ticks only append
bars newer than coverage_end (and backfill a missing prefix if needed).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.services.market_data.dataset_gc import has_stored_history, tail_is_fresh
from app.services.market_data.ingestion_runner import (
    run_databento_ingestion,
    run_finzdata_ingestion,
    run_ibkr_ingestion,
    run_yahoo_ingestion,
)
from app.services.market_data.live_feed import refresh_live_bars


def latest_dataset(session: Session, symbol: str, timeframe: str) -> HistoricalDataset | None:
    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol.upper())).scalar_one_or_none()
    if not inst:
        return None
    return session.execute(
        select(HistoricalDataset)
        .where(HistoricalDataset.instrument_id == inst.id, HistoricalDataset.timeframe == timeframe)
        .order_by(desc(HistoricalDataset.downloaded_at))
        .limit(1)
    ).scalar_one_or_none()


def download_history(
    session: Session,
    symbol: str,
    timeframe: str,
    *,
    start: datetime,
    end: datetime,
) -> tuple[HistoricalDataset, str]:
    """IBKR (if preferred) → FinzData → Databento → Yahoo. Merges into the stored series."""
    settings = get_settings()
    payload = {
        "instrument_symbol": symbol,
        "timeframe": timeframe,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    if settings.search_prefer_ibkr and settings.ibkr_configured:
        try:
            return run_ibkr_ingestion(session, payload), f"IBKR {timeframe}"
        except Exception:
            session.rollback()
    if settings.finzdata_configured:
        try:
            return run_finzdata_ingestion(session, payload), f"FinzData {timeframe}"
        except Exception:
            session.rollback()
    if settings.databento_configured:
        try:
            label = "Databento GLBX" + (" 1m→" + timeframe if timeframe != "1m" else f" →{timeframe}")
            return run_databento_ingestion(session, payload), label
        except Exception:
            session.rollback()
    return run_yahoo_ingestion(session, payload), f"Yahoo Finance {timeframe}"


def ensure_search_dataset(
    session: Session,
    symbol: str,
    timeframe: str,
    days: int,
) -> tuple[HistoricalDataset, str]:
    """Use stored bars when present; download full history only on first fill."""
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    ds = latest_dataset(session, symbol, timeframe)
    if ds and has_stored_history(
        coverage_start=ds.coverage_start,
        coverage_end=ds.coverage_end,
        row_count=int(ds.row_count or 0),
        window_start=start,
        window_end=end,
        timeframe=timeframe,
    ):
        added = _top_up_tail(session, ds, symbol, timeframe, end)
        ds = latest_dataset(session, symbol, timeframe) or ds
        bit = f" +{added} new" if added else ""
        return ds, f"stored {timeframe}{bit}"

    if ds and int(ds.row_count or 0) >= 80 and ds.coverage_start and ds.coverage_end:
        prefix_end = ds.coverage_start if ds.coverage_start.tzinfo else ds.coverage_start.replace(tzinfo=UTC)
        if prefix_end > start + timedelta(days=1):
            try:
                ds, _ = download_history(session, symbol, timeframe, start=start, end=prefix_end)
            except Exception:
                session.rollback()
                ds = latest_dataset(session, symbol, timeframe) or ds
        added = _top_up_tail(session, ds, symbol, timeframe, end)
        ds = latest_dataset(session, symbol, timeframe) or ds
        bit = f" +{added} new" if added else ""
        return ds, f"stored {timeframe} backfill{bit}"

    return download_history(session, symbol, timeframe, start=start, end=end)


def _top_up_tail(
    session: Session,
    dataset: HistoricalDataset,
    symbol: str,
    timeframe: str,
    now: datetime,
) -> int:
    if tail_is_fresh(dataset.coverage_end, now, timeframe):
        return 0
    try:
        result = refresh_live_bars(session, symbol, timeframe)
        return int(result.get("added") or 0)
    except Exception:
        session.rollback()
        return 0
