"""Incremental paper fills on new bars. Research simulation — not a live broker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.dsl import build_signal_context, session_keys_rth, signal_at_bar
from app.backtest.exits import (
    ManagedPosition,
    check_intrabar_exit,
    manage_at_bar_close,
    resolve_stop_target,
    time_stop_hit,
)
from app.models.instrument import Instrument
from app.services.futures_math import contracts_for_risk


@dataclass
class OpenTrade:
    direction: str
    qty: int
    entry_price: Decimal
    stop: Decimal
    target: Decimal
    entry_ts: datetime
    bars_held: int = 0
    initial_risk: Decimal = Decimal(0)


@dataclass
class SlotCursor:
    last_bar_ts: datetime | None
    position: OpenTrade | None


@dataclass
class ClosedFill:
    direction: str
    qty: int
    entry_ts: datetime
    entry_price: Decimal
    exit_ts: datetime
    exit_price: Decimal
    exit_reason: str
    net_pnl: Decimal


def _slip(price: Decimal, direction: str, side: str, tick: Decimal, ticks: int) -> Decimal:
    adj = tick * Decimal(ticks)
    if side == "entry":
        return price + adj if direction == "long" else price - adj
    return price - adj if direction == "long" else price + adj


def _net_pnl(
    entry: Decimal,
    exit_px: Decimal,
    direction: str,
    qty: int,
    instrument: Instrument,
    slip_ticks: int,
) -> Decimal:
    diff = exit_px - entry if direction == "long" else entry - exit_px
    gross = diff * instrument.multiplier * Decimal(qty)
    slip_cost = instrument.tick_size * Decimal(slip_ticks) * instrument.multiplier * Decimal(qty) * Decimal(2)
    commissions = instrument.default_commission_per_side * Decimal(2) * Decimal(qty)
    return gross - commissions - slip_cost


def apply_prop_rules(
    *,
    equity: Decimal,
    high_water: Decimal,
    day_start: Decimal,
    daily_loss_limit: Decimal,
    trailing_drawdown: Decimal,
    profit_target: Decimal,
    starting_equity: Decimal,
) -> tuple[Decimal, str]:
    """Return (high_water, status). status: active | daily_lock | breached | passed."""
    hw = max(high_water, equity)
    if hw - equity >= trailing_drawdown:
        return hw, "breached"
    if day_start - equity >= daily_loss_limit:
        return hw, "daily_lock"
    if equity - starting_equity >= profit_target:
        return hw, "passed"
    return hw, "active"


def advance_slot(
    spec: dict,
    bars: list[Bar],
    instrument: Instrument,
    cursor: SlotCursor,
    *,
    allow_entries: bool,
    slip_ticks: int = 1,
) -> tuple[SlotCursor, list[ClosedFill]]:
    """Walk only bars newer than cursor. Entries use the prior bar's signal (no lookahead)."""
    if len(bars) < 2:
        return cursor, []

    if cursor.last_bar_ts is None:
        cursor.last_bar_ts = bars[-1].ts
        return cursor, []

    index = {b.ts: i for i, b in enumerate(bars)}
    new_bars = [b for b in bars if b.ts > cursor.last_bar_ts]
    if not new_bars:
        return cursor, []

    keys = session_keys_rth(bars)
    tick = instrument.tick_size
    signal_ctx = build_signal_context(spec, bars, keys, instrument_tick=tick)
    fills: list[ClosedFill] = []
    pos = cursor.position

    for bar in new_bars:
        i = index[bar.ts]
        if pos is not None:
            exit_px, reason = check_intrabar_exit(pos.direction, pos.stop, pos.target, bar)
            if exit_px is None and i + 1 < len(bars) and keys[i + 1] != keys[i]:
                exit_px, reason = bar.close, "session_flatten"
            if exit_px is None:
                atr_now = signal_ctx.atr[i] if signal_ctx.atr else None
                managed = ManagedPosition(
                    direction=pos.direction,
                    entry=pos.entry_price,
                    stop=pos.stop,
                    target=pos.target,
                    bars_held=pos.bars_held,
                    initial_risk=pos.initial_risk or abs(pos.entry_price - pos.stop),
                )
                managed = manage_at_bar_close(managed, bar, spec, tick, atr_now)
                pos.stop = managed.stop
                pos.target = managed.target
                pos.bars_held = managed.bars_held
                pos.initial_risk = managed.initial_risk
                if time_stop_hit(managed, spec):
                    exit_px, reason = bar.close, "time_stop"
            if exit_px is not None and reason is not None:
                slipped = _slip(exit_px, pos.direction, "exit", tick, slip_ticks)
                fills.append(
                    ClosedFill(
                        pos.direction,
                        pos.qty,
                        pos.entry_ts,
                        pos.entry_price,
                        bar.ts,
                        slipped,
                        reason,
                        _net_pnl(pos.entry_price, slipped, pos.direction, pos.qty, instrument, slip_ticks),
                    )
                )
                pos = None
        elif allow_entries and i >= 1:
            sig = signal_at_bar(spec, bars, i - 1, keys, tick, signal_ctx)
            if sig:
                raw = bar.open
                dollar_risk = Decimal(str(spec.get("risk", {}).get("dollar_risk_per_trade", 75)))
                max_qty = int(spec.get("risk", {}).get("max_contracts", 1))
                qty = contracts_for_risk(raw, sig.stop_price, dollar_risk, instrument)
                qty = min(max(qty, 1 if qty > 0 else 0), max_qty)
                if qty >= 1:
                    entry_px = _slip(raw, sig.direction, "entry", tick, slip_ticks)
                    atr_sig = signal_ctx.atr[i - 1] if signal_ctx.atr else None
                    stop, target = resolve_stop_target(
                        spec,
                        direction=sig.direction,
                        entry_px=entry_px,
                        tick=tick,
                        atr=atr_sig,
                        fallback_stop=sig.stop_price + (entry_px - raw),
                        fallback_target=sig.target_price + (entry_px - raw),
                    )
                    pos = OpenTrade(
                        sig.direction,
                        qty,
                        entry_px,
                        stop,
                        target,
                        bar.ts,
                        0,
                        abs(entry_px - stop),
                    )
                    hit_px, hit_reason = check_intrabar_exit(pos.direction, pos.stop, pos.target, bar)
                    if hit_px is not None and hit_reason is not None:
                        reason = hit_reason
                        raw_exit = hit_px
                        slipped = _slip(raw_exit, pos.direction, "exit", tick, slip_ticks)
                        fills.append(
                            ClosedFill(
                                pos.direction,
                                pos.qty,
                                pos.entry_ts,
                                pos.entry_price,
                                bar.ts,
                                slipped,
                                reason,
                                _net_pnl(pos.entry_price, slipped, pos.direction, pos.qty, instrument, slip_ticks),
                            )
                        )
                        pos = None
                    else:
                        atr_now = signal_ctx.atr[i] if signal_ctx.atr else None
                        managed = ManagedPosition(
                            direction=pos.direction,
                            entry=pos.entry_price,
                            stop=pos.stop,
                            target=pos.target,
                            bars_held=pos.bars_held,
                            initial_risk=pos.initial_risk,
                        )
                        managed = manage_at_bar_close(managed, bar, spec, tick, atr_now)
                        pos.stop = managed.stop
                        pos.target = managed.target
                        pos.bars_held = managed.bars_held
                        if time_stop_hit(managed, spec):
                            slipped = _slip(bar.close, pos.direction, "exit", tick, slip_ticks)
                            fills.append(
                                ClosedFill(
                                    pos.direction,
                                    pos.qty,
                                    pos.entry_ts,
                                    pos.entry_price,
                                    bar.ts,
                                    slipped,
                                    "time_stop",
                                    _net_pnl(pos.entry_price, slipped, pos.direction, pos.qty, instrument, slip_ticks),
                                )
                            )
                            pos = None

        cursor.last_bar_ts = bar.ts

    cursor.position = pos
    return cursor, fills


def exit_open_on_quote(
    instrument: Instrument,
    cursor: SlotCursor,
    last_price: Decimal,
    ts: datetime,
    *,
    slip_ticks: int = 1,
) -> tuple[SlotCursor, list[ClosedFill]]:
    """Mark an open paper trade against the live last print (stop/target only, no new entries)."""
    pos = cursor.position
    if pos is None or last_price <= 0:
        return cursor, []
    bar = Bar(ts=ts, open=last_price, high=last_price, low=last_price, close=last_price, volume=0)
    exit_px, reason = check_intrabar_exit(pos.direction, pos.stop, pos.target, bar)
    if exit_px is None or reason is None:
        return cursor, []
    slipped = _slip(exit_px, pos.direction, "exit", instrument.tick_size, slip_ticks)
    fill = ClosedFill(
        pos.direction,
        pos.qty,
        pos.entry_ts,
        pos.entry_price,
        ts,
        slipped,
        reason,
        _net_pnl(pos.entry_price, slipped, pos.direction, pos.qty, instrument, slip_ticks),
    )
    cursor.position = None
    return cursor, [fill]
