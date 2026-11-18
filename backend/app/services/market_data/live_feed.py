"""Refresh paper-desk bars from the fastest configured feed (live first, delayed last)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.backtest.bars import Bar
from app.core.config import get_settings
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.services.market_data.bar_storage import append_bars_to_dataset
from app.services.market_data.finzdata_ingest import fetch_finzdata_ohlcv
from app.services.market_data.ibkr_ingest import bar_size_for_timeframe, fetch_ibkr_bars, fetch_ibkr_quote
from app.services.market_data.ingestion_runner import (
    run_finzdata_ingestion,
    run_ibkr_ingestion,
    run_twelvedata_ingestion,
    run_yahoo_ingestion,
)
from app.services.market_data.twelvedata_ingest import fetch_twelvedata_ohlcv, fetch_twelvedata_quote
from app.services.market_data.yahoo_ingest import bars_to_storage, fetch_yahoo_ohlcv

LIVE_LOOKBACK_HOURS = {"1m": 36, "5m": 72, "15m": 120, "1h": 240}
DELAYED_PROVIDERS = {"yahoo", "finzdata"}


def live_source_chain() -> list[str]:
    """IBKR (exchange) → Twelve Data (cloud live) → FinzData/Yahoo delayed."""
    settings = get_settings()
    chain: list[str] = []
    if settings.ibkr_configured:
        chain.append("ibkr")
    if settings.twelvedata_configured:
        chain.append("twelvedata")
    if settings.finzdata_configured:
        chain.append("finzdata")
    chain.append("yahoo")
    return chain


def classify_feed_quality(ts: datetime | None, *, session_open: bool, provider: str) -> str:
    if ts is None:
        return "unknown"
    aware = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    age = max(0, int((datetime.now(UTC) - aware).total_seconds()))
    if not session_open:
        return "session_closed"
    if provider in DELAYED_PROVIDERS:
        return "delayed" if age <= 30 * 60 else "stale"
    if age <= 90:
        return "live"
    if age <= 20 * 60:
        return "delayed"
    return "stale"


def _latest_dataset(session: Session, instrument_id, timeframe: str) -> HistoricalDataset | None:
    return session.execute(
        select(HistoricalDataset)
        .where(HistoricalDataset.instrument_id == instrument_id, HistoricalDataset.timeframe == timeframe)
        .order_by(desc(HistoricalDataset.downloaded_at))
        .limit(1)
    ).scalar_one_or_none()


def fetch_recent_bars(symbol: str, timeframe: str, start: datetime, end: datetime) -> tuple[list[Bar], str, str, str]:
    """Returns (bars, source_label, download_tf, provider)."""
    errors: list[str] = []
    for provider in live_source_chain():
        try:
            if provider == "ibkr":
                bars = fetch_ibkr_bars(
                    symbol,
                    start=start,
                    end=end,
                    bar_size=bar_size_for_timeframe(timeframe),
                    use_rth=False,
                )
                return bars, "ibkr", timeframe, "ibkr"
            if provider == "twelvedata":
                bars, root, tf = fetch_twelvedata_ohlcv(
                    instrument_symbol=symbol, start=start, end=end, target_timeframe=timeframe
                )
                if not bars:
                    raise ValueError("Twelve Data returned no bars")
                return bars, f"twelvedata:{root}", tf, "twelvedata"
            if provider == "finzdata":
                bars, root, tf = fetch_finzdata_ohlcv(
                    instrument_symbol=symbol, start=start, end=end, target_timeframe=timeframe
                )
                if not bars:
                    raise ValueError("FinzData returned no bars")
                return bars, f"finzdata:{root}", tf, "finzdata"
            bars, ticker, tf = fetch_yahoo_ohlcv(
                instrument_symbol=symbol, start=start, end=end, target_timeframe=timeframe
            )
            if not bars:
                raise ValueError("Yahoo returned no bars")
            return bars, f"yahoo:{ticker}", tf, "yahoo"
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            continue
    raise ValueError("All market data feeds failed: " + "; ".join(errors))


def fetch_live_quote(symbol: str) -> dict | None:
    """Last trade for mark-to-market. Prefers IBKR / Twelve Data over delayed Yahoo last bar."""
    settings = get_settings()
    if settings.ibkr_configured:
        try:
            return fetch_ibkr_quote(symbol)
        except Exception:
            pass
    if settings.twelvedata_configured:
        try:
            return fetch_twelvedata_quote(symbol)
        except Exception:
            pass
    return None


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
    payload = {
        "instrument_symbol": symbol.upper(),
        "timeframe": tf,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "use_rth": False,
    }
    if dataset is None:
        ds, provider = _bootstrap_dataset(session, payload)
        last = None
        quality = "unknown"
        return {
            "dataset_id": str(ds.id),
            "added": ds.row_count,
            "source": provider,
            "provider": provider,
            "quality": quality,
            "created": True,
            "last_close": last,
            "last_ts": None,
        }

    bars, source, download_tf, provider = fetch_recent_bars(symbol.upper(), tf, dataset.coverage_end - timedelta(hours=2) if dataset.coverage_end else start, end)
    stored = bars_to_storage(bars, source_timeframe=download_tf, target_timeframe=tf)
    added = append_bars_to_dataset(session, dataset, stored)
    last_bar = bars[-1] if bars else None
    quality = classify_feed_quality(last_bar.ts if last_bar else None, session_open=True, provider=provider)
    return {
        "dataset_id": str(dataset.id),
        "added": added,
        "source": source,
        "provider": provider,
        "quality": quality,
        "created": False,
        "coverage_end": dataset.coverage_end.isoformat() if dataset.coverage_end else None,
        "last_close": float(last_bar.close) if last_bar else None,
        "last_ts": last_bar.ts.isoformat() if last_bar else None,
    }


def _bootstrap_dataset(session: Session, payload: dict) -> tuple[HistoricalDataset, str]:
    errors: list[str] = []
    for provider in live_source_chain():
        try:
            if provider == "ibkr":
                return run_ibkr_ingestion(session, payload), "ibkr"
            if provider == "twelvedata":
                return run_twelvedata_ingestion(session, payload), "twelvedata"
            if provider == "finzdata":
                return run_finzdata_ingestion(session, payload), "finzdata"
            return run_yahoo_ingestion(session, payload), "yahoo"
        except Exception as exc:
            session.rollback()
            errors.append(f"{provider}: {exc}")
            continue
    raise ValueError("Could not create a live dataset: " + "; ".join(errors))
