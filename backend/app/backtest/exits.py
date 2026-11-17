"""Stop/target resolution and bar-close trade management (shared by backtest + paper)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.backtest.bars import Bar


@dataclass
class ManagedPosition:
    direction: str
    entry: Decimal
    stop: Decimal
    target: Decimal
    bars_held: int = 0
    initial_risk: Decimal = Decimal(0)


def ticks_from_atr(atr: Decimal, tick: Decimal, multiple: Decimal) -> int:
    if tick <= 0 or atr <= 0:
        return 2
    raw = (atr * multiple) / tick
    return max(2, int(raw.to_integral_value()))


def resolve_stop_target(
    spec: dict,
    *,
    direction: str,
    entry_px: Decimal,
    tick: Decimal,
    atr: Decimal | None,
    fallback_stop: Decimal,
    fallback_target: Decimal,
) -> tuple[Decimal, Decimal]:
    exit_spec = spec.get("exit") or {}
    stop_ticks = int(exit_spec.get("stop_ticks", 8))
    target_ticks = int(exit_spec.get("target_ticks", 16))
    if atr is not None and atr > 0:
        if exit_spec.get("stop_atr") is not None:
            stop_ticks = ticks_from_atr(atr, tick, Decimal(str(exit_spec["stop_atr"])))
        if exit_spec.get("target_atr") is not None:
            target_ticks = ticks_from_atr(atr, tick, Decimal(str(exit_spec["target_atr"])))
    else:
        return fallback_stop, fallback_target
    if direction == "long":
        return entry_px - stop_ticks * tick, entry_px + target_ticks * tick
    return entry_px + stop_ticks * tick, entry_px - target_ticks * tick


def check_intrabar_exit(direction: str, stop: Decimal, target: Decimal, bar: Bar) -> tuple[Decimal | None, str | None]:
    if direction == "long":
        if bar.low <= stop:
            return stop, "stop_loss"
        if bar.high >= target:
            return target, "take_profit"
    else:
        if bar.high >= stop:
            return stop, "stop_loss"
        if bar.low <= target:
            return target, "take_profit"
    return None, None


def manage_at_bar_close(
    pos: ManagedPosition,
    bar: Bar,
    spec: dict,
    tick: Decimal,
    atr: Decimal | None,
) -> ManagedPosition:
    """Tighten stop using this bar's range after it is complete (no intrabar lookahead)."""
    exit_spec = spec.get("exit") or {}
    pos.bars_held += 1
    risk = pos.initial_risk if pos.initial_risk > 0 else abs(pos.entry - pos.stop)
    if risk > 0 and exit_spec.get("breakeven_r") is not None:
        need = risk * Decimal(str(exit_spec["breakeven_r"]))
        if pos.direction == "long" and (bar.high - pos.entry) >= need:
            pos.stop = max(pos.stop, pos.entry + tick)
        elif pos.direction == "short" and (pos.entry - bar.low) >= need:
            pos.stop = min(pos.stop, pos.entry - tick)

    trail: Decimal | None = None
    if exit_spec.get("trail_ticks") is not None:
        trail = Decimal(int(exit_spec["trail_ticks"])) * tick
    elif exit_spec.get("trail_atr") is not None and atr is not None and atr > 0:
        trail = atr * Decimal(str(exit_spec["trail_atr"]))
    if trail is not None and trail > 0:
        if pos.direction == "long":
            pos.stop = max(pos.stop, bar.high - trail)
        else:
            pos.stop = min(pos.stop, bar.low + trail)
    return pos


def time_stop_hit(pos: ManagedPosition, spec: dict) -> bool:
    max_bars = (spec.get("exit") or {}).get("max_bars")
    if max_bars is None:
        return False
    return pos.bars_held >= int(max_bars)
