"""Declarative strategy DSL — no arbitrary code execution."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.backtest.bars import Bar
from app.backtest.indicators import ema_series, rsi_series, session_vwap


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
        "vwap_reversion",
        "rsi_reversion",
        "donchian_breakout",
        "consecutive_closes",
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
) -> EntrySignal | None:
    """Evaluate signal using data through bar index i (completed bar)."""
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
        fast = int(entry.get("fast_period", 9))
        slow = int(entry.get("slow_period", 21))
        closes = [b.close for b in bars[: i + 1]]
        fast_e = ema_series(closes, fast)
        slow_e = ema_series(closes, slow)
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
        range_minutes = int(entry.get("range_minutes", 15))
        or_map = opening_range_bounds(bars, session_keys, range_minutes)
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
        vwap = session_vwap(bars[: i + 1], session_keys[: i + 1])
        if vwap[i] is None:
            return None
        if bar.close >= vwap[i] + dev_ticks * tick:
            return pack("short", "vwap_stretch_short", None if invert else vwap[i])
        if bar.close <= vwap[i] - dev_ticks * tick:
            return pack("long", "vwap_stretch_long", None if invert else vwap[i])
        return None

    if entry_type == "rsi_reversion":
        period = int(entry.get("period", 14))
        oversold = Decimal(str(entry.get("oversold", 30)))
        overbought = Decimal(str(entry.get("overbought", 70)))
        closes = [b.close for b in bars[: i + 1]]
        series = rsi_series(closes, period)
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

    raise ValueError(f"Unsupported entry.type {entry_type}")