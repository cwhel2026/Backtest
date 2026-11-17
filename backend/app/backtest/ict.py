"""Session dealing range, premium/discount, and order-block zones (ICT-inspired)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.backtest.bars import Bar


@dataclass
class SessionRange:
    high: Decimal
    low: Decimal
    equilibrium: Decimal


@dataclass
class OrderBlockZone:
    direction: str  # bullish | bearish
    top: Decimal
    bottom: Decimal
    formed_bar: int


def session_dealing_ranges(
    bars: list[Bar],
    session_keys: list[str],
) -> dict[str, SessionRange]:
    """Per RTH session: running high/low → equilibrium."""
    hi: dict[str, Decimal] = {}
    lo: dict[str, Decimal] = {}
    for i, b in enumerate(bars):
        key = session_keys[i]
        hi[key] = max(hi.get(key, b.high), b.high)
        lo[key] = min(lo.get(key, b.low), b.low)
    out: dict[str, SessionRange] = {}
    for key in hi:
        h, l = hi[key], lo[key]
        out[key] = SessionRange(h, l, (h + l) / Decimal(2))
    return out


def range_position(bar_close: Decimal, sr: SessionRange) -> Decimal:
    """0 = range low, 1 = range high."""
    span = sr.high - sr.low
    if span <= 0:
        return Decimal("0.5")
    return (bar_close - sr.low) / span


def discover_order_blocks(
    bars: list[Bar],
    *,
    instrument_tick: Decimal,
    displacement_ticks: int = 12,
    lookback: int = 8,
) -> list[OrderBlockZone]:
    """Last opposing candle before a displacement leg."""
    disp = instrument_tick * Decimal(displacement_ticks)
    zones: list[OrderBlockZone] = []
    for i in range(2, len(bars) - 1):
        b = bars[i]
        body = abs(b.close - b.open)
        if body < disp:
            continue
        if b.close > b.open:
            for j in range(i - 1, max(0, i - lookback), -1):
                prior = bars[j]
                if prior.close < prior.open:
                    zones.append(
                        OrderBlockZone("bullish", prior.open, prior.high, j)
                    )
                    break
        elif b.close < b.open:
            for j in range(i - 1, max(0, i - lookback), -1):
                prior = bars[j]
                if prior.close > prior.open:
                    zones.append(
                        OrderBlockZone("bearish", prior.low, prior.open, j)
                    )
                    break
    return zones


def order_block_retest(
    bar: Bar,
    bar_index: int,
    zones: list[OrderBlockZone],
    *,
    max_age_bars: int,
    side: str = "both",
) -> str | None:
    for z in zones:
        if z.formed_bar >= bar_index:
            continue
        if bar_index - z.formed_bar > max_age_bars:
            continue
        if z.direction == "bullish" and side in ("both", "long"):
            if bar.low <= z.top and bar.low >= z.bottom and bar.close > z.top:
                return "long"
        if z.direction == "bearish" and side in ("both", "short"):
            if bar.high >= z.bottom and bar.high <= z.top and bar.close < z.bottom:
                return "short"
    return None