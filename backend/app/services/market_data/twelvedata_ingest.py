"""Near-live CME futures OHLCV via Twelve Data (HTTP). Paid plans are real-time; free is delayed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx

from app.backtest.bars import Bar
from app.core.config import get_settings

TWELVEDATA_SERIES_URL = "https://api.twelvedata.com/time_series"
TWELVEDATA_QUOTE_URL = "https://api.twelvedata.com/quote"
CHICAGO = ZoneInfo("America/Chicago")

INTERVAL_FOR_TF = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
}

# Twelve Data CME roots — continuous-style front month.
TWELVEDATA_SYMBOL = {
    "NQ": "NQ",
    "MNQ": "MNQ",
    "ES": "ES",
    "MES": "MES",
}


def twelvedata_symbol(instrument_symbol: str) -> str:
    root = instrument_symbol.strip().upper().lstrip("/")
    return TWELVEDATA_SYMBOL.get(root, root)


def interval_for_timeframe(timeframe: str) -> str:
    if timeframe not in INTERVAL_FOR_TF:
        raise ValueError(f"Twelve Data does not map timeframe {timeframe}")
    return INTERVAL_FOR_TF[timeframe]


def bars_from_payload(payload: object, *, tz_name: str = "America/Chicago") -> list[Bar]:
    if not isinstance(payload, dict):
        raise ValueError("Twelve Data returned an unexpected JSON shape")
    if payload.get("status") == "error" or payload.get("code"):
        raise ValueError(str(payload.get("message") or payload.get("status") or "Twelve Data error"))
    rows = payload.get("values")
    if not isinstance(rows, list):
        raise ValueError("Twelve Data time series missing values")
    tz = ZoneInfo(tz_name) if tz_name else CHICAGO
    bars: list[Bar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("datetime") or row.get("timestamp") or row.get("time")
        if raw is None:
            continue
        try:
            ts = _parse_ts(raw, tz)
            o = Decimal(str(row["open"]))
            h = Decimal(str(row["high"]))
            low = Decimal(str(row["low"]))
            c = Decimal(str(row["close"]))
        except (KeyError, TypeError, ValueError):
            continue
        vol_raw = row.get("volume") or 0
        try:
            volume = int(Decimal(str(vol_raw)))
        except (ArithmeticError, ValueError):
            volume = 0
        bars.append(Bar(ts=ts, open=o, high=h, low=low, close=c, volume=volume))
    bars.sort(key=lambda b: b.ts)
    return bars


def quote_from_payload(payload: object, *, tz_name: str = "America/Chicago") -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Twelve Data quote returned an unexpected JSON shape")
    if payload.get("status") == "error" or (payload.get("code") and not payload.get("close") and not payload.get("price")):
        raise ValueError(str(payload.get("message") or "Twelve Data quote error"))
    last = payload.get("close") or payload.get("price") or payload.get("last")
    if last is None:
        raise ValueError("Twelve Data quote missing last price")
    tz = ZoneInfo(tz_name) if tz_name else CHICAGO
    raw_ts = payload.get("datetime") or payload.get("timestamp")
    ts = _parse_ts(raw_ts, tz) if raw_ts else datetime.now(UTC)
    return {
        "symbol": str(payload.get("symbol") or ""),
        "last": float(last),
        "open": float(payload["open"]) if payload.get("open") not in (None, "") else None,
        "high": float(payload["high"]) if payload.get("high") not in (None, "") else None,
        "low": float(payload["low"]) if payload.get("low") not in (None, "") else None,
        "volume": int(Decimal(str(payload.get("volume") or 0))),
        "ts": ts,
        "source": "twelvedata",
    }


def _parse_ts(value: object, tz: ZoneInfo) -> datetime:
    if isinstance(value, (int, float)):
        ts = datetime.fromtimestamp(float(value), tz=UTC)
        if ts.year < 2000:
            ts = datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
        return ts
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(UTC)


def fetch_twelvedata_ohlcv(
    *,
    instrument_symbol: str,
    start: datetime,
    end: datetime,
    target_timeframe: str = "1m",
) -> tuple[list[Bar], str, str]:
    settings = get_settings()
    key = (settings.twelvedata_api_key or "").strip()
    if not key:
        raise ValueError("TWELVEDATA_API_KEY is not set")
    root = twelvedata_symbol(instrument_symbol)
    interval = interval_for_timeframe(target_timeframe)
    minutes = max(1, int((end - start).total_seconds() / 60))
    outputsize = min(5000, max(30, minutes + 5))
    response = httpx.get(
        TWELVEDATA_SERIES_URL,
        params={
            "symbol": root,
            "exchange": "CME",
            "interval": interval,
            "outputsize": outputsize,
            "timezone": "UTC",
            "apikey": key,
            "order": "ASC",
        },
        timeout=25.0,
    )
    response.raise_for_status()
    payload = response.json()
    bars = bars_from_payload(payload, tz_name="UTC")
    start_u = start if start.tzinfo else start.replace(tzinfo=UTC)
    end_u = end if end.tzinfo else end.replace(tzinfo=UTC)
    bars = [b for b in bars if start_u <= b.ts <= end_u + timedelta(minutes=1)]
    return bars, root, target_timeframe


def fetch_twelvedata_quote(instrument_symbol: str) -> dict:
    settings = get_settings()
    key = (settings.twelvedata_api_key or "").strip()
    if not key:
        raise ValueError("TWELVEDATA_API_KEY is not set")
    root = twelvedata_symbol(instrument_symbol)
    response = httpx.get(
        TWELVEDATA_QUOTE_URL,
        params={
            "symbol": root,
            "exchange": "CME",
            "interval": "1min",
            "timezone": "UTC",
            "apikey": key,
        },
        timeout=15.0,
    )
    response.raise_for_status()
    payload = response.json()
    quote = quote_from_payload(payload, tz_name="UTC")
    quote["symbol"] = root
    return quote
