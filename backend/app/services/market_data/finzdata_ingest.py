"""FinzData historical futures OHLCV (continuous series). Free plan is daily-only."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx

from app.backtest.bars import Bar, TIMEFRAME_MINUTES, aggregate_bars
from app.core.config import get_settings

FINZDATA_BARS_URL = "https://api.finzdata.com/v1/futures/bars"
EASTERN = ZoneInfo("America/New_York")

INTERVAL_FOR_TF = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1hour",
}


def finzdata_root(instrument_symbol: str) -> str:
    return instrument_symbol.strip().upper().lstrip("/")


def interval_for_timeframe(timeframe: str) -> str:
    if timeframe not in INTERVAL_FOR_TF:
        raise ValueError(f"FinzData does not map timeframe {timeframe}")
    return INTERVAL_FOR_TF[timeframe]


def _as_rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "bars", "results", "items"):
            raw = payload.get(key)
            if isinstance(raw, list):
                return [row for row in raw if isinstance(row, dict)]
    raise ValueError("FinzData returned an unexpected JSON shape")


def _parse_ts(value: object) -> datetime:
    if value is None:
        raise ValueError("FinzData bar missing timestamp")
    if isinstance(value, (int, float)):
        ts = datetime.fromtimestamp(float(value), tz=UTC)
        if ts.year < 2000:
            ts = datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
        return ts
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN)
    return dt.astimezone(UTC)


def bars_from_payload(payload: object) -> list[Bar]:
    bars: list[Bar] = []
    for row in _as_rows(payload):
        ts_raw = row.get("timestamp") or row.get("datetime") or row.get("time") or row.get("ts") or row.get("date")
        try:
            ts = _parse_ts(ts_raw)
            o = Decimal(str(row["open"] if "open" in row else row["Open"]))
            h = Decimal(str(row["high"] if "high" in row else row["High"]))
            low = Decimal(str(row["low"] if "low" in row else row["Low"]))
            c = Decimal(str(row["close"] if "close" in row else row["Close"]))
        except (KeyError, TypeError, ValueError):
            continue
        vol_raw = row.get("volume", row.get("Volume", row.get("vol", 0))) or 0
        try:
            volume = int(Decimal(str(vol_raw)))
        except (ArithmeticError, ValueError):
            volume = 0
        bars.append(Bar(ts=ts, open=o, high=h, low=low, close=c, volume=volume))
    bars.sort(key=lambda b: b.ts)
    return bars


def fetch_finzdata_ohlcv(
    *,
    instrument_symbol: str,
    start: datetime,
    end: datetime,
    target_timeframe: str = "5m",
    client: httpx.Client | None = None,
) -> tuple[list[Bar], str, str]:
    settings = get_settings()
    key = (settings.finzdata_api_key or "").strip()
    if not key:
        raise ValueError("FINZDATA_API_KEY not configured")
    if target_timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"Unsupported timeframe {target_timeframe}")

    interval = interval_for_timeframe(target_timeframe)
    root = finzdata_root(instrument_symbol)
    params = {
        "root": root,
        "continuous": "true",
        "interval": interval,
        "start": start.astimezone(UTC).date().isoformat(),
        "end": end.astimezone(UTC).date().isoformat(),
        "format": "json",
    }
    own_client = client is None
    http = client or httpx.Client(timeout=90.0)
    try:
        response = http.get(FINZDATA_BARS_URL, params=params, headers={"X-API-Key": key})
    finally:
        if own_client:
            http.close()

    if response.status_code == 401:
        raise ValueError("FinzData rejected FINZDATA_API_KEY (401).")
    if response.status_code == 403:
        raise ValueError(
            "FinzData free plan is last-30-days daily bars only. "
            "1m/5m MNQ search needs a one-market ($59) or Futures Complete purchase."
        )
    if response.status_code == 429:
        raise ValueError("FinzData daily call limit reached.")
    if response.status_code >= 400:
        detail = response.text[:240]
        raise ValueError(f"FinzData HTTP {response.status_code}: {detail}")

    bars = bars_from_payload(response.json())
    return bars, root, target_timeframe


def bars_to_storage(
    bars: list[Bar],
    *,
    source_timeframe: str,
    target_timeframe: str,
) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]]:
    if not bars:
        return []
    if source_timeframe != target_timeframe:
        bars = aggregate_bars(bars, target_timeframe)
    return [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in bars]
