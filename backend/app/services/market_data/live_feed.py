"""Refresh the latest dataset for a symbol/timeframe with new live (delayed) bars."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.services.market_data.bar_storage import append_bars_to_dataset
from app.services.market_data.finzdata_ingest import fetch_finzdata_ohlcv
from app.services.market_data.ingestion_runner import run_finzdata_ingestion, run_yahoo_ingestion
from app.services.market_data.yahoo_ingest import bars_to_storage, fetch_yahoo_ohlcv

LIVE_LOOKBACK_HOURS = {"1m": 36, "5m": 72, "15m": 120, "1h": 240}


def _latest_dataset(session: Session, instrument_id, timeframe: str) -> HistoricalDataset | None:
    return session.execute(
        select(HistoricalDataset)
        .where(HistoricalDataset.instrument_id == instrument_id, HistoricalDataset.timeframe == timeframe)
        .order_by(desc(HistoricalDataset.downloaded_at))
        .limit(1)
    ).scalar_one_or_none()


def fetch_recent_bars(symbol: str, timeframe: str, start: datetime, end: datetime):
    settings = get_settings()
    if settings.finzdata_configured:
        try:
            bars, root, tf = fetch_finzdata_ohlcv(
                instrument_symbol=symbol, start=start, end=end, target_timeframe=timeframe
            )
            return bars, f"finzdata:{root}", tf
        except Exception:
            pass
    bars, ticker, tf = fetch_yahoo_ohlcv(
        instrument_symbol=symbol, start=start, end=end, target_timeframe=timeframe
    )
    return bars, f"yahoo:{ticker}", tf


def refresh_live_bars(session: Session, symbol: str, timeframe: str = "5m") -> dict:
    """Append new bars onto the latest dataset, or ingest a short window if none exist."""
    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol.upper())).scalar_one_or_none()
    if not inst:
        raise ValueError(f"Unknown instrument {symbol}")
    tf = timeframe if timeframe in LIVE_LOOKBACK_HOURS else "5m"
    hours = LIVE_LOOKBACK_HOURS[tf]
    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)
    dataset = _latest_dataset(session, inst.id, tf)
    if dataset is None:
        payload = {
            "instrument_symbol": symbol.upper(),
            "timeframe": tf,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        settings = get_settings()
        if settings.finzdata_configured:
            try:
                ds = run_finzdata_ingestion(session, payload)
                return {"dataset_id": str(ds.id), "added": ds.row_count, "source": "finzdata", "created": True}
            except Exception:
                session.rollback()
        ds = run_yahoo_ingestion(session, payload)
        return {"dataset_id": str(ds.id), "added": ds.row_count, "source": "yahoo", "created": True}

    fetch_start = dataset.coverage_end - timedelta(hours=2) if dataset.coverage_end else start
    bars, source, download_tf = fetch_recent_bars(symbol.upper(), tf, fetch_start, end)
    stored = bars_to_storage(bars, source_timeframe=download_tf, target_timeframe=tf)
    added = append_bars_to_dataset(session, dataset, stored)
    return {
        "dataset_id": str(dataset.id),
        "added": added,
        "source": source,
        "created": False,
        "coverage_end": dataset.coverage_end.isoformat() if dataset.coverage_end else None,
    }
