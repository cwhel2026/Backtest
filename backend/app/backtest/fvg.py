"""Fair value gap (3-candle imbalance) detection — ICT-style, no lookahead on signal bar."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.backtest.bars import Bar


@dataclass
class FvgZone:
    direction: str  # bullish | bearish
    bottom: Decimal
    top: Decimal
    formed_bar: int


def discover_fvg_zones(
    bars: list[Bar],
    *,
    instrument_tick: Decimal,
    min_gap_ticks: int = 4,
) -> list[FvgZone]:
    min_gap = instrument_tick * Decimal(min_gap_ticks)
    zones: list[FvgZone] = []
    for i in range(2, len(bars)):
        b0 = bars[i - 2]
        b2 = bars[i]
        if b2.low > b0.high:
            gap = b2.low - b0.high
            if gap >= min_gap:
                zones.append(FvgZone("bullish", b0.high, b2.low, i))
        if b2.high < b0.low:
            gap = b0.low - b2.high
            if gap >= min_gap:
                zones.append(FvgZone("bearish", b2.high, b0.low, i))
    return zones


def fvg_retest_signal(
    bar: Bar,
    bar_index: int,
    zones: list[FvgZone],
    *,
    max_age_bars: int,
    side: str = "both",
) -> str | None:
    """Return long | short | None on retest + rejection of an open gap."""
    for z in zones:
        if z.formed_bar >= bar_index:
            continue
        age = bar_index - z.formed_bar
        if age > max_age_bars:
            continue
        mid = (z.top + z.bottom) / Decimal(2)
        if z.direction == "bullish" and side in ("both", "long"):
            touched = bar.low <= z.top and bar.low >= z.bottom
            if touched and bar.close > mid:
                return "long"
        if z.direction == "bearish" and side in ("both", "short"):
            touched = bar.high >= z.bottom and bar.high <= z.top
            if touched and bar.close < mid:
                return "short"
    return None