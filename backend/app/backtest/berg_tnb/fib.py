"""Fakeout (0.079) and entry Fibonacci helpers."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal


def round_tick(px: Decimal, tick: Decimal, mode: str = "nearest") -> Decimal:
    steps = px / tick
    if mode == "up":
        steps = steps.to_integral_value(rounding=ROUND_CEILING)
    elif mode == "down":
        steps = steps.to_integral_value(rounding=ROUND_FLOOR)
    else:
        steps = steps.quantize(Decimal("1"))
    return steps * tick


def fib_fakeout_level(high: Decimal, low: Decimal, bias: str, ratio: Decimal = Decimal("0.079")) -> Decimal:
    """Bullish: high→low measure, level below high. Bearish: low→high measure, level above low."""
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