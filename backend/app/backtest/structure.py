"""Market structure: swings, sweeps, BOS, Fibonacci — no repaint past confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtest.bars import Bar


@dataclass(frozen=True)
class SwingPoint:
    kind: str  # high | low
    index: int
    price: Decimal
    confirmed_at: int  # bar index when swing became knowable (right bars closed)


def confirmed_swings(bars: list[Bar], left: int = 2, right: int = 2) -> list[SwingPoint]:
    """Swings confirm only after `right` bars close — safe for live replay."""
    out: list[SwingPoint] = []
    if len(bars) < left + right + 1:
        return out
    for i in range(left, len(bars) - right):
        window = bars[i - left : i + right + 1]
        center = bars[i]
        if center.high >= max(b.high for b in window):
            if center.high > max(b.high for b in window if b is not center):
                out.append(SwingPoint("high", i, center.high, i + right))
        if center.low <= min(b.low for b in window):
            if center.low < min(b.low for b in window if b is not center):
                out.append(SwingPoint("low", i, center.low, i + right))
    return out


def session_prior_extremes(
    bars: list[Bar],
    session_keys: list[str],
    i: int,
) -> tuple[Decimal | None, Decimal | None]:
    """Prior completed session high/low (excludes current session)."""
    if i < 1:
        return None, None
    prior_day = session_keys[i - 1]
    hi = lo = None
    for j in range(i):
        if session_keys[j] != prior_day:
            continue
        hi = bars[j].high if hi is None else max(hi, bars[j].high)
        lo = bars[j].low if lo is None else min(lo, bars[j].low)
    return hi, lo


def swings_visible_at(swings: list[SwingPoint], bar_index: int) -> list[SwingPoint]:
    return [s for s in swings if s.confirmed_at <= bar_index]


def fib_retrace(low: Decimal, high: Decimal, ratio: Decimal) -> Decimal:
    """Retrace from high toward low for bullish impulse (low→high); level = high - ratio*(high-low)."""
    return high - ratio * (high - low)


def fib_retrace_bear(low: Decimal, high: Decimal, ratio: Decimal) -> Decimal:
    return low + ratio * (high - low)


def break_of_structure(
    swings: list[SwingPoint],
    up_to_index: int,
    direction: str,
) -> SwingPoint | None:
    """Most recent confirmed swing broken by structure (using swings confirmed before index)."""
    usable = [s for s in swings if s.confirmed_at <= up_to_index]
    if not usable:
        return None
    if direction == "long":
        highs = [s for s in usable if s.kind == "high"]
        return highs[-1] if highs else None
    lows = [s for s in usable if s.kind == "low"]
    return lows[-1] if lows else None


@dataclass
class SweepSetup:
    direction: str
    sweep_extreme: Decimal
    reclaimed_level: Decimal
    signal_ts: datetime
    impulse_low: Decimal
    impulse_high: Decimal
    reason: str


def detect_liquidity_sweep_reversal(
    bars: list[Bar],
    i: int,
    session_keys: list[str],
    tick: Decimal,
    *,
    sweep_ticks: int = 2,
    fib_ratio: Decimal = Decimal("0.618"),
    require_bos: bool = False,
    swings: list[SwingPoint] | None = None,
) -> SweepSetup | None:
    if i < 3:
        return None
    prior_hi, prior_lo = session_prior_extremes(bars, session_keys, i)
    bar = bars[i]
    sweep = tick * Decimal(sweep_ticks)
    if prior_lo is not None and bar.low < prior_lo - sweep and bar.close > prior_lo:
        impulse_low = bar.low
        impulse_high = max(b.high for b in bars[max(0, i - 8) : i + 1])
        if require_bos and swings:
            anchor = break_of_structure(swings, i, "long")
            if anchor is None or bar.close <= anchor.price:
                return None
        limit = fib_retrace(impulse_low, impulse_high, fib_ratio)
        return SweepSetup(
            "long",
            impulse_low,
            prior_lo,
            bar.ts,
            impulse_low,
            impulse_high,
            "sweep_prior_session_low",
        )
    if prior_hi is not None and bar.high > prior_hi + sweep and bar.close < prior_hi:
        impulse_high = bar.high
        impulse_low = min(b.low for b in bars[max(0, i - 8) : i + 1])
        if require_bos and swings:
            anchor = break_of_structure(swings, i, "short")
            if anchor is None or bar.close >= anchor.price:
                return None
        return SweepSetup(
            "short",
            impulse_high,
            prior_hi,
            bar.ts,
            impulse_low,
            impulse_high,
            "sweep_prior_session_high",
        )
    return None


def sweep_limit_price(setup: SweepSetup, fib_ratio: Decimal = Decimal("0.618")) -> Decimal:
    if setup.direction == "long":
        return fib_retrace(setup.impulse_low, setup.impulse_high, fib_ratio)
    return fib_retrace_bear(setup.impulse_low, setup.impulse_high, fib_ratio)


@dataclass
class AnchorBosSetup:
    direction: str
    anchor: SwingPoint
    signal_ts: datetime
    impulse_low: Decimal
    impulse_high: Decimal
    reason: str


def detect_anchor_bos_retrace(
    bars: list[Bar],
    i: int,
    swings: list[SwingPoint],
    *,
    require_close_confirm: bool = True,
) -> AnchorBosSetup | None:
    bar = bars[i]
    usable = [s for s in swings if s.confirmed_at <= i]
    if len(usable) < 2:
        return None
    last_hi = next((s for s in reversed(usable) if s.kind == "high"), None)
    last_lo = next((s for s in reversed(usable) if s.kind == "low"), None)
    if last_hi and bar.close > last_hi.price:
        impulse_low = min(b.low for b in bars[last_hi.index : i + 1])
        return AnchorBosSetup(
            "long",
            last_hi,
            bar.ts,
            impulse_low,
            bar.high,
            f"bos_above_swing_high_{last_hi.index}",
        )
    if last_lo and bar.close < last_lo.price:
        impulse_high = max(b.high for b in bars[last_lo.index : i + 1])
        return AnchorBosSetup(
            "short",
            last_lo,
            bar.ts,
            bar.low,
            impulse_high,
            f"bos_below_swing_low_{last_lo.index}",
        )
    return None


def anchor_limit_price(setup: AnchorBosSetup, fib_ratio: Decimal = Decimal("0.618")) -> Decimal:
    if setup.direction == "long":
        return fib_retrace(setup.impulse_low, setup.impulse_high, fib_ratio)
    return fib_retrace_bear(setup.impulse_low, setup.impulse_high, fib_ratio)