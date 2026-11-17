"""Declarative strategy DSL — no arbitrary code execution."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.backtest.bars import Bar
from app.backtest.indicators import ema_series, session_vwap


@dataclass
class EntrySignal:
    direction: str  # long | short
    signal_ts: datetime
    stop_price: Decimal
    target_price: Decimal
    reason: str


def validate_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("name", "instrument_symbol", "timeframe", "entry", "exit", "risk"):
        if key not in spec:
            errors.append(f"Missing {key}")
    entry = spec.get("entry") or {}
    if "type" not in entry:
        errors.append("entry.type required")
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
    bar = bars[i]
    tick = instrument_tick

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
            entry_px = bar.close
            return EntrySignal(
                "long",
                bar.ts,
                entry_px - stop_ticks * tick,
                entry_px + target_ticks * tick,
                "ema_cross_up",
            )
        if crossed_dn:
            entry_px = bar.close
            return EntrySignal(
                "short",
                bar.ts,
                entry_px + stop_ticks * tick,
                entry_px - target_ticks * tick,
                "ema_cross_down",
            )
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
            entry_px = bar.close
            return EntrySignal(
                "long",
                bar.ts,
                entry_px - stop_ticks * tick,
                entry_px + target_ticks * tick,
                "or_breakout_long",
            )
        if side in ("both", "short") and bar.close < or_low:
            entry_px = bar.close
            return EntrySignal(
                "short",
                bar.ts,
                entry_px + stop_ticks * tick,
                entry_px - target_ticks * tick,
                "or_breakout_short",
            )
        return None

    if entry_type == "vwap_reversion":
        dev_ticks = Decimal(str(entry.get("deviation_ticks", 12)))
        vwap = session_vwap(bars[: i + 1], session_keys[: i + 1])
        if vwap[i] is None:
            return None
        if bar.close >= vwap[i] + dev_ticks * tick:
            entry_px = bar.close
            return EntrySignal(
                "short",
                bar.ts,
                entry_px + stop_ticks * tick,
                vwap[i],
                "vwap_stretch_short",
            )
        if bar.close <= vwap[i] - dev_ticks * tick:
            entry_px = bar.close
            return EntrySignal(
                "long",
                bar.ts,
                entry_px - stop_ticks * tick,
                vwap[i],
                "vwap_stretch_long",
            )
        return None

    raise ValueError(f"Unsupported entry.type {entry_type}")