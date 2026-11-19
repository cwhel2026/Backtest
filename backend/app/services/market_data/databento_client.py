"""Databento GLBX.MDP3 client: cost, symbology, retries — no price stitching."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import databento as db
from databento import BentoClientError, BentoError

from app.core.config import get_settings
from app.backtest.bars import Bar
from app.services.market_data.databento_ingest import (
    DATABENTO_FUTURES_DATASET,
    DATABENTO_OHLCV_SCHEMA,
    databento_continuous_symbol,
)

# Micro roots (phase 1) — architecture supports extension to full-size roots.
DATABENTO_ROOT_SYMBOLS: dict[str, str] = {
    "MNQ": "MNQ",
    "MES": "MES",
    "MGC": "MGC",
    "NQ": "NQ",
    "ES": "ES",
    "GC": "GC",
    "6E": "6E",
    "6B": "6B",
    "6J": "6J",
    "6A": "6A",
    "6C": "6C",
    "6S": "6S",
}


def validate_root_symbol(instrument_symbol: str) -> str:
    root = instrument_symbol.strip().upper()
    if root not in DATABENTO_ROOT_SYMBOLS:
        supported = ", ".join(sorted(DATABENTO_ROOT_SYMBOLS))
        raise ValueError(f"Unsupported Databento root {root!r}. Supported: {supported}")
    return root


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def client(api_key: str | None = None) -> db.Historical:
    settings = get_settings()
    key = (api_key or settings.databento_api_key).strip()
    if not key:
        raise ValueError("Databento API key not configured (DATABENTO_API_KEY)")
    return db.Historical(key)


@dataclass
class DatabentoCostQuote:
    usd: float
    source: str
    continuous_symbol: str
    dataset: str
    schema: str
    note: str
    gbp: float | None = None
    gbp_rate: float | None = None

    def to_dict(self) -> dict:
        return {
            "estimated_usd": self.usd,
            "estimated_gbp": self.gbp,
            "gbp_usd_rate": self.gbp_rate,
            "provider": "databento",
            "databento_dataset": self.dataset,
            "databento_symbol": self.continuous_symbol,
            "schema": self.schema,
            "source": self.source,
            "requires_approval": True,
            "note": self.note,
        }


def quote_download_cost(
    instrument_symbol: str,
    start: datetime,
    end: datetime,
    *,
    api_key: str | None = None,
    gbp_usd_rate: float | None = None,
) -> DatabentoCostQuote:
    """Official metadata.get_cost when a key is present; heuristic offline otherwise."""
    root = validate_root_symbol(instrument_symbol)
    symbol = databento_continuous_symbol(root)
    start_utc = _ensure_utc(start)
    end_utc = _ensure_utc(end)
    if end_utc <= start_utc:
        raise ValueError("end must be after start")

    settings = get_settings()
    rate = gbp_usd_rate
    if rate is None and settings.gbp_usd_rate:
        rate = float(settings.gbp_usd_rate)

    key = (api_key or settings.databento_api_key).strip()
    if not key:
        days = max(1, int((end_utc - start_utc).total_seconds() // 86400))
        usd = float(Decimal("0.25") * Decimal(days))
        return DatabentoCostQuote(
            usd=usd,
            source="heuristic",
            continuous_symbol=symbol,
            dataset=DATABENTO_FUTURES_DATASET,
            schema=DATABENTO_OHLCV_SCHEMA,
            note="No API key — rough estimate only. Configure DATABENTO_API_KEY for official get_cost.",
            gbp=(usd / rate) if rate else None,
            gbp_rate=rate,
        )

    try:
        c = client(key)
        raw = c.metadata.get_cost(
            dataset=DATABENTO_FUTURES_DATASET,
            start=start_utc,
            end=end_utc,
            symbols=symbol,
            schema=DATABENTO_OHLCV_SCHEMA,
            stype_in="continuous",
        )
        usd = float(raw) if raw is not None else 0.0
        source = "databento.get_cost"
        note = "Estimate from Databento metadata.get_cost — final billing may differ."
    except (BentoClientError, BentoError, ValueError) as exc:
        raise ValueError(f"Databento cost check failed: {exc}") from exc

    return DatabentoCostQuote(
        usd=usd,
        source=source,
        continuous_symbol=symbol,
        dataset=DATABENTO_FUTURES_DATASET,
        schema=DATABENTO_OHLCV_SCHEMA,
        note=note,
        gbp=(usd / rate) if rate else None,
        gbp_rate=rate,
    )


def check_dataset_range(start: datetime, end: datetime, *, api_key: str | None = None) -> dict[str, Any]:
    """Light entitlement / coverage probe via get_dataset_range."""
    start_utc = _ensure_utc(start)
    end_utc = _ensure_utc(end)
    key = (api_key or get_settings().databento_api_key).strip()
    if not key:
        return {"available": False, "reason": "DATABENTO_API_KEY not configured"}
    try:
        c = client(key)
        out = c.metadata.get_dataset_range(dataset=DATABENTO_FUTURES_DATASET)
        return {"available": True, "dataset_range": out, "requested": {"start": start_utc.isoformat(), "end": end_utc.isoformat()}}
    except (BentoClientError, BentoError) as exc:
        return {"available": False, "reason": str(exc)}


def fetch_ohlcv_1m_with_retries(
    instrument_symbol: str,
    start: datetime,
    end: datetime,
    *,
    api_key: str | None = None,
    max_attempts: int = 3,
    retry_sleep_s: float = 2.0,
) -> tuple[list[Bar], dict]:
    """Download 1m OHLCV; returns bars and symbology/rollover metadata (not back-adjusted)."""
    validate_root_symbol(instrument_symbol)
    start_utc = _ensure_utc(start)
    end_utc = _ensure_utc(end)
    symbol = databento_continuous_symbol(instrument_symbol)
    key = (api_key or get_settings().databento_api_key).strip()
    if not key:
        raise ValueError("Databento API key not configured")

    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            c = client(key)
            store = c.timeseries.get_range(
                dataset=DATABENTO_FUTURES_DATASET,
                schema=DATABENTO_OHLCV_SCHEMA,
                symbols=symbol,
                start=start_utc,
                end=end_utc,
                stype_in="continuous",
                stype_out="instrument_id",
            )
            frame = store.to_df()
            meta = _extract_symbology_metadata(store)
            bars = _frame_to_bars(frame)
            return bars, {
                **meta,
                "databento_dataset": DATABENTO_FUTURES_DATASET,
                "databento_continuous_symbol": symbol,
                "databento_actual_symbol_type": "instrument_id",
                "back_adjusted": False,
                "price_stitching": False,
            }
        except (BentoClientError, BentoError) as exc:
            last_err = exc
            if attempt < max_attempts:
                time.sleep(retry_sleep_s * attempt)
            continue
    raise ValueError(f"Databento download failed after {max_attempts} attempts: {last_err}") from last_err


def _frame_to_bars(frame) -> list[Bar]:
    if frame is None or frame.empty:
        return []
    bars: list[Bar] = []
    for ts, row in frame.iterrows():
        bar_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if getattr(bar_ts, "tzinfo", None) is None:
            bar_ts = bar_ts.replace(tzinfo=UTC)
        else:
            bar_ts = bar_ts.astimezone(UTC)
        vol = int(row.get("volume", 0))
        if vol < 0:
            raise ValueError("negative volume in Databento row")
        bars.append(
            Bar(
                ts=bar_ts,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=vol,
            )
        )
    return sorted(bars, key=lambda b: b.ts)


def _extract_symbology_metadata(store) -> dict:
    """Best-effort mapping / rollover intervals — prices are exchange as-is (no stitch)."""
    rollovers: list[dict] = []
    try:
        meta = getattr(store, "metadata", None)
        if meta and getattr(meta, "mappings", None):
            for sym_in, entries in meta.mappings.items():
                for entry in entries:
                    start = getattr(entry, "start", None) or entry.get("start") if isinstance(entry, dict) else None
                    end = getattr(entry, "end", None) or entry.get("end") if isinstance(entry, dict) else None
                    raw = getattr(entry, "symbol", None) or (entry.get("symbol") if isinstance(entry, dict) else None)
                    if raw:
                        rollovers.append(
                            {
                                "continuous_input": sym_in,
                                "contract_instrument_id": str(raw),
                                "start": str(start) if start is not None else None,
                                "end": str(end) if end is not None else None,
                            }
                        )
    except Exception:
        pass
    return {"rollover_events": rollovers, "symbology_note": "Continuous symbol; see rollover_events for underlying ids"}