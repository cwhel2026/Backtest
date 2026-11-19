"""Licensed historical OHLCV download via Databento (CME Globex MDP 3)."""

from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.bars import Bar, TIMEFRAME_MINUTES, aggregate_bars

DATABENTO_FUTURES_DATASET = "GLBX.MDP3"
DATABENTO_OHLCV_SCHEMA = "ohlcv-1m"


def databento_continuous_symbol(instrument_symbol: str) -> str:
    return f"{instrument_symbol.strip().upper()}.c.0"


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fetch_databento_ohlcv_1m(
    *,
    instrument_symbol: str,
    start: datetime,
    end: datetime,
    api_key: str | None = None,
) -> list[Bar]:
    """Download 1-minute OHLCV bars; returns empty list only when the API returns no rows."""
    from app.services.market_data.databento_client import fetch_ohlcv_1m_with_retries

    bars, _meta = fetch_ohlcv_1m_with_retries(instrument_symbol, start, end, api_key=api_key)
    return bars


def fetch_databento_ohlcv_1m_with_meta(
    *,
    instrument_symbol: str,
    start: datetime,
    end: datetime,
    api_key: str | None = None,
) -> tuple[list[Bar], dict]:
    from app.services.market_data.databento_client import fetch_ohlcv_1m_with_retries

    return fetch_ohlcv_1m_with_retries(instrument_symbol, start, end, api_key=api_key)


def bars_for_timeframe(bars_1m: list[Bar], timeframe: str) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]]:
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"Unsupported timeframe {timeframe}. Use one of: {', '.join(TIMEFRAME_MINUTES)}")

    if timeframe == "1m":
        working = bars_1m
    else:
        working = aggregate_bars(bars_1m, timeframe)

    return [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in working]