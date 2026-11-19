"""Futures trade cost accounting — slippage in fills, not deducted twice."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.instrument import Instrument


def apply_slippage(price: Decimal, direction: str, side: str, tick: Decimal, ticks: int) -> Decimal:
    """Move execution price against the trader by `ticks` on each side."""
    adj = tick * Decimal(ticks)
    if side == "entry":
        if direction == "long":
            return price + adj
        return price - adj
    if direction == "long":
        return price - adj
    return price + adj


def gross_pnl(
    entry: Decimal,
    exit_px: Decimal,
    direction: str,
    qty: int,
    multiplier: Decimal,
) -> Decimal:
    diff = exit_px - entry if direction == "long" else entry - exit_px
    return diff * multiplier * Decimal(qty)


def informational_slippage(
    ref_entry: Decimal,
    exec_entry: Decimal,
    ref_exit: Decimal,
    exec_exit: Decimal,
    direction: str,
    qty: int,
    multiplier: Decimal,
) -> Decimal:
    """Dollar slippage vs unslipped reference fills (report only — not subtracted again)."""
    ref_gross = gross_pnl(ref_entry, ref_exit, direction, qty, multiplier)
    exec_gross = gross_pnl(exec_entry, exec_exit, direction, qty, multiplier)
    return ref_gross - exec_gross


@dataclass
class TradeSettlement:
    gross_pnl: Decimal
    commissions: Decimal
    slippage: Decimal
    net_pnl: Decimal


def settle_trade(
    *,
    direction: str,
    qty: int,
    instrument: Instrument,
    ref_entry: Decimal,
    exec_entry: Decimal,
    ref_exit: Decimal,
    exec_exit: Decimal,
    commission_per_side: Decimal,
) -> TradeSettlement:
    gross = gross_pnl(exec_entry, exec_exit, direction, qty, instrument.multiplier)
    slip = informational_slippage(
        ref_entry, exec_entry, ref_exit, exec_exit, direction, qty, instrument.multiplier
    )
    commissions = commission_per_side * Decimal(2) * Decimal(qty)
    net = gross - commissions
    return TradeSettlement(gross_pnl=gross, commissions=commissions, slippage=slip, net_pnl=net)


def round_to_tick(price: Decimal, tick: Decimal, *, mode: str = "nearest") -> Decimal:
    if tick <= 0:
        return price
    steps = price / tick
    if mode == "down":
        steps = steps.to_integral_value(rounding="ROUND_FLOOR")
    elif mode == "up":
        steps = steps.to_integral_value(rounding="ROUND_CEILING")
    else:
        steps = steps.quantize(Decimal("1"))
    return steps * tick