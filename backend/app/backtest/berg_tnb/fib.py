"""Fakeout (0.079) and entry Fibonacci — TradingView orientation per Berg PDF step 6/8."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.backtest.bars import Bar


def round_tick(px: Decimal, tick: Decimal, mode: str = "nearest") -> Decimal:
    steps = px / tick
    if mode == "up":
        steps = steps.to_integral_value(rounding=ROUND_CEILING)
    elif mode == "down":
        steps = steps.to_integral_value(rounding=ROUND_FLOOR)
    else:
        steps = steps.quantize(Decimal("1"))
    return steps * tick


def fakeout_anchor_extremes(
    bars: list[Bar],
    *,
    session_high: Decimal,
    session_low: Decimal,
    from_index: int,
    to_index: int,
) -> tuple[Decimal, Decimal]:
    """PDF step 6: extremes between previous session range and price action since sweep."""
    hi = session_high
    lo = session_low
    for j in range(max(0, from_index), to_index + 1):
        hi = max(hi, bars[j].high)
        lo = min(lo, bars[j].low)
    return hi, lo


def fib_fakeout_level(high: Decimal, low: Decimal, bias: str, ratio: Decimal = Decimal("0.079")) -> Decimal:
    """
    TradingView fib: anchor 0 at first point, 1 at second.
    Bullish PDF: drag high → low → level at 0.079 from top (near high).
    Bearish PDF: drag low → high → level at 0.079 from bottom (near low).
    """
    span = high - low
    if span <= 0:
        raise ValueError("invalid fib span")
    if bias == "bullish":
        return high - span * ratio
    return low + span * ratio


def fib_entry_limit(
    low: Decimal,
    high: Decimal,
    bias: str,
    ratio: Decimal,
    tick: Decimal,
) -> Decimal:
    """PDF step 8 golden pocket retracement on session extreme → post-BOS extreme."""
    span = high - low
    if span <= 0:
        raise ValueError("invalid entry fib span")
    if bias == "bullish":
        return round_tick(high - span * ratio, tick, "down")
    return round_tick(low + span * ratio, tick, "up")


def fakeout_touched(bias: str, level: Decimal, low: Decimal, high: Decimal) -> bool:
    if bias == "bullish":
        return low <= level
    return high >= level