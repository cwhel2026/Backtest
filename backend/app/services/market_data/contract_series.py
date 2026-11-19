"""Futures series resolution — continuous vs outright, rollover metadata (no silent stitch)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from app.backtest.bars import Bar

RollRule = Literal["volume", "calendar", "open_interest"]


class PriceSeriesKind(str, Enum):
    CONTINUOUS_UNADJUSTED = "continuous_unadjusted"
    CONTINUOUS_ADJUSTED = "continuous_adjusted"
    OUTRIGHT = "outright"


@dataclass(frozen=True)
class SeriesSelection:
    root: str
    kind: PriceSeriesKind = PriceSeriesKind.CONTINUOUS_UNADJUSTED
    roll_rule: RollRule = "volume"
    roll_index: int = 0
    contract_month: str | None = None
    outright_symbol: str | None = None


def databento_stype_in(selection: SeriesSelection) -> str:
    if selection.kind == PriceSeriesKind.OUTRIGHT:
        return "raw_symbol"
    return "continuous"


def databento_symbol(selection: SeriesSelection) -> str:
    root = selection.root.strip().upper()
    if selection.kind == PriceSeriesKind.OUTRIGHT:
        if selection.outright_symbol:
            return selection.outright_symbol
        if selection.contract_month:
            return f"{root}{selection.contract_month}"
        raise ValueError("outright series requires contract_month or outright_symbol")
    return f"{root}.c.{selection.roll_index}"


def series_metadata(selection: SeriesSelection) -> dict:
    return {
        "series_kind": selection.kind.value,
        "price_adjustment": "none" if selection.kind == PriceSeriesKind.CONTINUOUS_UNADJUSTED else "provider_or_explicit",
        "roll_rule": selection.roll_rule,
        "roll_index": selection.roll_index,
        "back_adjusted": selection.kind == PriceSeriesKind.CONTINUOUS_ADJUSTED,
        "stitching_applied": False,
        "databento_symbol": databento_symbol(selection),
        "databento_stype_in": databento_stype_in(selection),
    }


def selection_from_ingest_payload(payload: dict, instrument_symbol: str) -> SeriesSelection:
    kind_s = str(payload.get("series_kind") or PriceSeriesKind.CONTINUOUS_UNADJUSTED.value)
    try:
        kind = PriceSeriesKind(kind_s)
    except ValueError:
        kind = PriceSeriesKind.CONTINUOUS_UNADJUSTED
    return SeriesSelection(
        root=instrument_symbol,
        kind=kind,
        roll_rule=payload.get("roll_rule") or "volume",
        roll_index=int(payload.get("roll_index") or 0),
        contract_month=payload.get("contract_month"),
        outright_symbol=payload.get("outright_symbol"),
    )


def detect_rollover_jumps(
    bars: list[Bar],
    rollover_events: list[dict],
    *,
    tick_size: Decimal,
    jump_ticks: int = 80,
) -> list[dict]:
    """Flag large open gaps near known rollover boundaries (expected, not data errors)."""
    if len(bars) < 2 or not rollover_events:
        return []
    hits: list[dict] = []
    threshold = tick_size * jump_ticks
    for i in range(1, len(bars)):
        gap = abs(bars[i].open - bars[i - 1].close)
        if gap < threshold:
            continue
        hits.append(
            {
                "index": i,
                "ts": bars[i].ts.isoformat(),
                "gap_points": float(gap),
                "expected_roll": True,
                "note": "Possible unadjusted continuous roll — not auto-corrected",
            }
        )
    return hits[:50]