"""Declarative strategy DSL — no arbitrary code execution."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.backtest.bars import Bar
from app.backtest.fvg import discover_fvg_zones, fvg_retest_signal
from app.backtest.indicators import bollinger_series, ema_series, rsi_series, session_vwap


@dataclass
class EntrySignal:
    direction: str  # long | short
    signal_ts: datetime
    stop_price: Decimal
    target_price: Decimal
    reason: str


ENTRY_TYPES = frozenset(
    {
        "opening_range_breakout",
        "ema_crossover",
        "ema_pullback",
        "vwap_reversion",
        "rsi_reversion",
        "donchian_breakout",
        "consecutive_closes",
        "fair_value_gap",
        "bollinger_reversion",
        "liquidity_sweep",
    }
)
SUPPORTED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h"})


def validate_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("name", "instrument_symbol", "timeframe", "entry", "exit", "risk"):
        if key not in spec:
            errors.append(f"Missing {key}")
    if spec.get("timeframe") not in SUPPORTED_TIMEFRAMES:
        errors.append(f"timeframe must be one of {sorted(SUPPORTED_TIMEFRAMES)}")
    entry = spec.get("entry") or {}
    if "type" not in entry:
        errors.append("entry.type required")
    elif entry.get("type") not in ENTRY_TYPES:
        errors.append(f"entry.type must be one of {sorted(ENTRY_TYPES)}")
    exit_spec = spec.get("exit") or {}
    if "stop_ticks" not in exit_spec or "target_ticks" not in exit_spec:
        errors.append("exit.stop_ticks and exit.target_ticks required")
    return errors


def session_keys_rth(bars: list[Bar], tz: str = "America/Chicago") -> list[str]:
    zone = ZoneInfo(tz)
    keys: list[str] = []
    for b in bars:
        local = b.ts.astimezone(zone)
        keys.append(local.date().isoformat())
    return keys


def opening_range_bounds(
    bars: list[Bar], session_keys: list[str], range_minutes: int, tz: str = "America/Chicago"
) -> dict[str, tuple[Decimal, Decimal, int]]:
    """Per session: (or_high, or_low, last_or_bar_index)."""
    zone = ZoneInfo(tz)
    open_minutes = 8 * 60 + 30
    out: dict[str, tuple[Decimal, Decimal, int]] = {}
    for i, b in enumerate(bars):
        local = b.ts.astimezone(zone)
        mins = local.hour * 60 + local.minute
        offset = mins - open_minutes
        if offset < 0 or offset >= range_minutes:
            continue
        key = session_keys[i]
        if key in out:
            hi = max(b.high, out[key][0])
            lo = min(b.low, out[key][1])
        else:
            hi, lo = b.high, b.low
        out[key] = (hi, lo, i)
    return out


@dataclass
class SignalContext:
    """Precomputed indicator series for O(n) per-bar signal evaluation."""

    session_keys: list[str]
    or_map: dict[str, tuple[Decimal, Decimal, int]] | None = None
    fast_e: list[Decimal | None] | None = None
    slow_e: list[Decimal | None] | None = None
    vwap: list[Decimal | None] | None = None
    rsi: list[Decimal | None] | None = None
    fvg_zones: list | None = None
    bb_upper: list[Decimal | None] | None = None
    bb_lower: list[Decimal | None] | None = None


def build_signal_context(
    spec: dict,
    bars: list[Bar],
    session_keys: list[str] | None = None,
    *,
    instrument_tick: Decimal | None = None,
) -> SignalContext:
    """Compute indicators once per backtest (avoids O(n²) prefix recomputation)."""
    if session_keys is None:
        session_keys = session_keys_rth(bars)
    entry = spec["entry"]
    entry_type = entry.get("type")
    ctx = SignalContext(session_keys=session_keys)
    if entry_type == "opening_range_breakout":
        range_minutes = int(entry.get("range_minutes", 15))
        ctx.or_map = opening_range_bounds(bars, session_keys, range_minutes)
    elif entry_type in ("ema_crossover", "ema_pullback"):
        closes = [b.close for b in bars]
        fast = int(entry.get("fast_period", 9))
        slow = int(entry.get("slow_period", 21))
        ctx.fast_e = ema_series(closes, fast)
        ctx.slow_e = ema_series(closes, slow)
    elif entry_type == "fair_value_gap":
        min_gap = int(entry.get("min_gap_ticks", 4))
        tick = instrument_tick or Decimal("0.25")
        ctx.fvg_zones = discover_fvg_zones(bars, instrument_tick=tick, min_gap_ticks=min_gap)
    elif entry_type == "bollinger_reversion":
        closes = [b.close for b in bars]
        period = int(entry.get("period", 20))
        mult = Decimal(str(entry.get("std_mult", 2)))
        _mid, upper, lower = bollinger_series(closes, period, mult)
        ctx.bb_upper = upper
        ctx.bb_lower = lower
    elif entry_type == "vwap_reversion":
        ctx.vwap = session_vwap(bars, session_keys)
    elif entry_type == "rsi_reversion":
        closes = [b.close for b in bars]
        period = int(entry.get("period", 14))
        ctx.rsi = rsi_series(closes, period)
    return ctx


def _pack_signal(
    *,
    direction: str,
    ts: datetime,
    entry_px: Decimal,
    stop_ticks: int,
    target_ticks: int,
    tick: Decimal,
    reason: str,
    invert: bool,
    target_override: Decimal | None = None,
) -> EntrySignal:
    if invert:
        direction = "short" if direction == "long" else "long"
        reason = f"rev_{reason}"
        target_override = None
    if direction == "long":
        stop = entry_px - stop_ticks * tick
        target = target_override if target_override is not None else entry_px + target_ticks * tick
    else:
        stop = entry_px + stop_ticks * tick
        target = target_override if target_override is not None else entry_px - target_ticks * tick
    return EntrySignal(direction, ts, stop, target, reason)


def signal_at_bar(
    spec: dict,
    bars: list[Bar],
    i: int,
    session_keys: list[str],
    instrument_tick: Decimal,
    ctx: SignalContext | None = None,
) -> EntrySignal | None:
    """Evaluate signal using data through bar index i (completed bar)."""
    if ctx is None:
        ctx = build_signal_context(spec, bars, session_keys)
    entry = spec["entry"]
    exit_spec = spec["exit"]
    entry_type = entry.get("type")
    stop_ticks = int(exit_spec.get("stop_ticks", 8))
    target_ticks = int(exit_spec.get("target_ticks", 16))
    invert = bool(entry.get("invert"))
    bar = bars[i]
    tick = instrument_tick

    def pack(direction: str, reason: str, target_override: Decimal | None = None) -> EntrySignal:
        return _pack_signal(
            direction=direction,
            ts=bar.ts,
            entry_px=bar.close,
            stop_ticks=stop_ticks,
            target_ticks=target_ticks,
            tick=tick,
            reason=reason,
            invert=invert,
            target_override=target_override,
        )

    if entry_type == "ema_crossover":
        fast_e = ctx.fast_e
        slow_e = ctx.slow_e
        if fast_e is None or slow_e is None:
            raise ValueError("SignalContext missing EMA series")
        if fast_e[i] is None or slow_e[i] is None or i < 1:
            return None
        if fast_e[i - 1] is None or slow_e[i - 1] is None:
            return None
        crossed_up = fast_e[i - 1] <= slow_e[i - 1] and fast_e[i] > slow_e[i]
        crossed_dn = fast_e[i - 1] >= slow_e[i - 1] and fast_e[i] < slow_e[i]
        if crossed_up:
            return pack("long", "ema_cross_up")
        if crossed_dn:
            return pack("short", "ema_cross_down")
        return None

    if entry_type == "opening_range_breakout":
        or_map = ctx.or_map
        if or_map is None:
            raise ValueError("SignalContext missing opening range map")
        key = session_keys[i]
        if key not in or_map:
            return None
        or_high, or_low, last_or = or_map[key]
        if i <= last_or:
            return None
        side = entry.get("side", "both")
        if side in ("both", "long") and bar.close > or_high:
            return pack("long", "or_breakout_long")
        if side in ("both", "short") and bar.close < or_low:
            return pack("short", "or_breakout_short")
        return None

    if entry_type == "vwap_reversion":
        dev_ticks = Decimal(str(entry.get("deviation_ticks", 12)))
        vwap = ctx.vwap
        if vwap is None:
            raise ValueError("SignalContext missing VWAP series")
        if vwap[i] is None:
            return None
        if bar.close >= vwap[i] + dev_ticks * tick:
            return pack("short", "vwap_stretch_short", None if invert else vwap[i])
        if bar.close <= vwap[i] - dev_ticks * tick:
            return pack("long", "vwap_stretch_long", None if invert else vwap[i])
        return None

    if entry_type == "rsi_reversion":
        oversold = Decimal(str(entry.get("oversold", 30)))
        overbought = Decimal(str(entry.get("overbought", 70)))
        series = ctx.rsi
        if series is None:
            raise ValueError("SignalContext missing RSI series")
        if series[i] is None or i < 1 or series[i - 1] is None:
            return None
        rsi_now = series[i]
        rsi_prev = series[i - 1]
        assert rsi_now is not None and rsi_prev is not None
        if rsi_prev >= oversold and rsi_now < oversold:
            return pack("long", "rsi_oversold")
        if rsi_prev <= overbought and rsi_now > overbought:
            return pack("short", "rsi_overbought")
        return None

    if entry_type == "donchian_breakout":
        lookback = int(entry.get("lookback", 20))
        if i < lookback:
            return None
        window = bars[i - lookback : i]
        highest = max(b.high for b in window)
        lowest = min(b.low for b in window)
        if bar.close > highest:
            return pack("long", "donchian_break_high")
        if bar.close < lowest:
            return pack("short", "donchian_break_low")
        return None

    if entry_type == "consecutive_closes":
        count = int(entry.get("count", 3))
        if i < count:
            return None
        ups = all(bars[i - k].close > bars[i - k - 1].close for k in range(count))
        dns = all(bars[i - k].close < bars[i - k - 1].close for k in range(count))
        if ups:
            return pack("long", "streak_up")
        if dns:
            return pack("short", "streak_down")
        return None

    if entry_type == "fair_value_gap":
        zones = ctx.fvg_zones
        if not zones:
            return None
        max_age = int(entry.get("max_age_bars", 48))
        side = str(entry.get("side", "both"))
        direction = fvg_retest_signal(bar, i, zones, max_age_bars=max_age, side=side)
        if direction == "long":
            return pack("long", "fvg_retest_long")
        if direction == "short":
            return pack("short", "fvg_retest_short")
        return None

    if entry_type == "bollinger_reversion":
        upper = ctx.bb_upper
        lower = ctx.bb_lower
        if upper is None or lower is None or upper[i] is None or lower[i] is None:
            return None
        if i < 1:
            return None
        touch_hi = bar.high >= upper[i]
        touch_lo = bar.low <= lower[i]
        if touch_hi and bar.close < upper[i]:
            return pack("short", "bb_upper_reject")
        if touch_lo and bar.close > lower[i]:
            return pack("long", "bb_lower_reject")
        return None

    if entry_type == "ema_pullback":
        fast_e = ctx.fast_e
        slow_e = ctx.slow_e
        if fast_e is None or slow_e is None or fast_e[i] is None or slow_e[i] is None or i < 2:
            return None
        if fast_e[i - 1] is None or slow_e[i - 1] is None:
            return None
        uptrend = fast_e[i - 1] > slow_e[i - 1]
        dntrend = fast_e[i - 1] < slow_e[i - 1]
        ema_px = fast_e[i]
        assert ema_px is not None
        if uptrend and bar.low <= ema_px <= bar.high and bar.close > ema_px:
            return pack("long", "ema_pullback_long")
        if dntrend and bar.low <= ema_px <= bar.high and bar.close < ema_px:
            return pack("short", "ema_pullback_short")
        return None

    if entry_type == "liquidity_sweep":
        lookback = int(entry.get("lookback", 12))
        sweep_ticks = int(entry.get("sweep_ticks", 2))
        if i < lookback + 1:
            return None
        window = bars[i - lookback : i]
        swing_hi = max(b.high for b in window)
        swing_lo = min(b.low for b in window)
        sweep = tick * Decimal(sweep_ticks)
        if bar.low < swing_lo - sweep and bar.close > swing_lo:
            return pack("long", "liq_sweep_low")
        if bar.high > swing_hi + sweep and bar.close < swing_hi:
            return pack("short", "liq_sweep_high")
        return None

    raise ValueError(f"Unsupported entry.type {entry_type}")