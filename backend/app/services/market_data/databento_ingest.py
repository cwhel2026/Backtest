"""Licensed historical OHLCV download via Databento (CME Globex MDP 3)."""

from datetime import UTC, datetime
from decimal import Decimal

import databento as db
from databento import BentoClientError, BentoError

from app.backtest.bars import Bar, TIMEFRAME_MINUTES, aggregate_bars
from app.core.config import get_settings

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
    settings = get_settings()
    key = (api_key or settings.databento_api_key).strip()
    if not key:
        raise ValueError("Databento API key not configured")

    start_utc = _ensure_utc(start)
    end_utc = _ensure_utc(end)
    if end_utc <= start_utc:
        raise ValueError("end must be after start")

    symbol = databento_continuous_symbol(instrument_symbol)
    client = db.Historical(key)
    try:
        store = client.timeseries.get_range(
            dataset=DATABENTO_FUTURES_DATASET,
            schema=DATABENTO_OHLCV_SCHEMA,
            symbols=symbol,
            start=start_utc,
            end=end_utc,
            stype_in="continuous",
            stype_out="instrument_id",
        )
        frame = store.to_df()
    except BentoClientError as exc:
        raise ValueError(f"Databento rejected request: {exc}") from exc
    except BentoError as exc:
        raise ValueError(f"Databento error: {exc}") from exc

    if frame is None or frame.empty:
        return []

    bars: list[Bar] = []
    for ts, row in frame.iterrows():
        bar_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if getattr(bar_ts, "tzinfo", None) is None:
            bar_ts = bar_ts.replace(tzinfo=UTC)
        else:
            bar_ts = bar_ts.astimezone(UTC)
        bars.append(
            Bar(
                ts=bar_ts,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=int(row.get("volume", 0)),
            )
        )
    return sorted(bars, key=lambda b: b.ts)


def bars_for_timeframe(bars_1m: list[Bar], timeframe: str) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]]:
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"Unsupported timeframe {timeframe}. Use one of: {', '.join(TIMEFRAME_MINUTES)}")

    if timeframe == "1m":
        working = bars_1m
    else:
        working = aggregate_bars(bars_1m, timeframe)

    return [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in working]