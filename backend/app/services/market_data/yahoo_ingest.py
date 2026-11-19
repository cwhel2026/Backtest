"""Free delayed futures OHLCV via Yahoo Finance (yfinance). Not exchange-licensed."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import yfinance as yf

from app.backtest.bars import Bar, TIMEFRAME_MINUTES, aggregate_bars

# Registry symbols → Yahoo continuous futures tickers (same root symbol + =F).
YAHOO_TICKER_SUFFIX = "=F"

YAHOO_MAX_RANGE_DAYS = {
    "1m": 7,
    "5m": 60,
    "1h": 730,
}


def yahoo_futures_ticker(instrument_symbol: str) -> str:
    return f"{instrument_symbol.strip().upper()}{YAHOO_TICKER_SUFFIX}"


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def choose_yahoo_download_timeframe(start: datetime, end: datetime, target_timeframe: str) -> str:
    """Pick the finest Yahoo interval that covers the requested window."""
    start_u = _ensure_utc(start)
    end_u = _ensure_utc(end)
    if end_u <= start_u:
        raise ValueError("end must be after start")

    days = (end_u - start_u).total_seconds() / 86400
    target_m = TIMEFRAME_MINUTES.get(target_timeframe, 5)

    if target_m <= 1 and days <= YAHOO_MAX_RANGE_DAYS["1m"]:
        return "1m"
    if target_m <= 5 and days <= YAHOO_MAX_RANGE_DAYS["5m"]:
        return "5m"
    if days <= YAHOO_MAX_RANGE_DAYS["1h"]:
        return "1h"
    if target_timeframe == "1h" and days <= YAHOO_MAX_RANGE_DAYS["1h"]:
        return "1h"
    raise ValueError(
        f"Yahoo free data: range is {days:.1f} days. Use ≤7 days for 1m, ≤60 days for 5m strategies, "
        f"or shorten the window."
    )


def _interval_to_timeframe(interval: str) -> str:
    mapping = {"1m": "1m", "5m": "5m", "1h": "1h", "60m": "1h", "90m": "1h"}
    return mapping.get(interval, "5m")


def fetch_yahoo_ohlcv(
    *,
    instrument_symbol: str,
    start: datetime,
    end: datetime,
    target_timeframe: str = "5m",
) -> tuple[list[Bar], str, str]:
    """Returns (bars, yahoo_ticker, download_timeframe)."""
    start_u = _ensure_utc(start)
    end_u = _ensure_utc(end)
    interval = choose_yahoo_download_timeframe(start_u, end_u, target_timeframe)
    ticker = yahoo_futures_ticker(instrument_symbol)

    # yfinance end is exclusive; add a cushion so the last session is included
    fetch_end = end_u + timedelta(minutes=1)
    df = yf.Ticker(ticker).history(
        start=start_u,
        end=fetch_end,
        interval=interval,
        auto_adjust=False,
    )
    if df is None or df.empty:
        return [], ticker, _interval_to_timeframe(interval)

    bars: list[Bar] = []
    for ts, row in df.iterrows():
        bar_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if bar_ts.tzinfo is None:
            bar_ts = bar_ts.replace(tzinfo=UTC)
        else:
            bar_ts = bar_ts.astimezone(UTC)
        vol = row.get("Volume", 0)
        bars.append(
            Bar(
                ts=bar_ts,
                open=Decimal(str(row["Open"])),
                high=Decimal(str(row["High"])),
                low=Decimal(str(row["Low"])),
                close=Decimal(str(row["Close"])),
                volume=int(vol) if vol == vol else 0,
            )
        )
    bars.sort(key=lambda b: b.ts)
    return bars, ticker, _interval_to_timeframe(interval)


def bars_to_storage(
    bars: list[Bar],
    *,
    source_timeframe: str,
    target_timeframe: str,
) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]]:
    if not bars:
        return []

    if target_timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"Unsupported timeframe {target_timeframe}")

    src_m = TIMEFRAME_MINUTES[source_timeframe]
    tgt_m = TIMEFRAME_MINUTES[target_timeframe]

    if src_m > tgt_m:
        raise ValueError(
            f"Cannot build {target_timeframe} dataset from Yahoo {source_timeframe} bars — request a shorter range."
        )

    if source_timeframe == target_timeframe:
        working = bars
    elif source_timeframe == "1m":
        working = aggregate_bars(bars, target_timeframe) if target_timeframe != "1m" else bars
    else:
        # Coarser download (e.g. 5m) → coarser target only
        working = aggregate_bars(bars, target_timeframe) if src_m < tgt_m else bars

    return [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in working]