"""Incremental paper fills on new bars. Research simulation — not a live broker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.dsl import session_keys_rth, signal_at_bar
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
    fills: list[ClosedFill] = []
    pos = cursor.position

    for bar in new_bars:
        i = index[bar.ts]
        if pos is not None:
            exit_px = None
            reason = None
            if pos.direction == "long":
                if bar.low <= pos.stop:
                    exit_px, reason = pos.stop, "stop_loss"
                elif bar.high >= pos.target:
                    exit_px, reason = pos.target, "take_profit"
            else:
                if bar.high >= pos.stop:
                    exit_px, reason = pos.stop, "stop_loss"
                elif bar.low <= pos.target:
                    exit_px, reason = pos.target, "take_profit"
            if exit_px is None and i + 1 < len(bars) and keys[i + 1] != keys[i]:
                exit_px, reason = bar.close, "session_flatten"
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
            sig = signal_at_bar(spec, bars, i - 1, keys, tick)
            if sig:
                raw = bar.open
                dollar_risk = Decimal(str(spec.get("risk", {}).get("dollar_risk_per_trade", 75)))
                max_qty = int(spec.get("risk", {}).get("max_contracts", 1))
                qty = contracts_for_risk(raw, sig.stop_price, dollar_risk, instrument)
                qty = min(max(qty, 1 if qty > 0 else 0), max_qty)
                if qty >= 1:
                    entry_px = _slip(raw, sig.direction, "entry", tick, slip_ticks)
                    shift = entry_px - raw
                    pos = OpenTrade(
                        sig.direction,
                        qty,
                        entry_px,
                        sig.stop_price + shift,
                        sig.target_price + shift,
                        bar.ts,
                    )
                    stop_hit = bar.low <= pos.stop if pos.direction == "long" else bar.high >= pos.stop
                    target_hit = bar.high >= pos.target if pos.direction == "long" else bar.low <= pos.target
                    if stop_hit or target_hit:
                        reason = "stop_loss" if stop_hit else "take_profit"
                        raw_exit = pos.stop if stop_hit else pos.target
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

        cursor.last_bar_ts = bar.ts

    cursor.position = pos
    return cursor, fills
