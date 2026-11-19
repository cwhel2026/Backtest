"""Deterministic OHLC order-state simulator for video strategies.

OHLC assumptions (research labels, not live guarantees):
- Limit entry: touch on bar low/high implies fill at limit price (eligibility only).
- Same bar as fill: no stop/target until a later bar (entry before exit).
- Ambiguous bar (stop and target both touched): stop evaluated before target.
- Gap through stop: exit at bar open when open is past stop (worse fill).
- Partial fills: full qty on first eligible touch (no tick-level queue).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from app.backtest.bars import Bar
from app.backtest.costs import apply_slippage, settle_trade
from app.backtest.exits import check_intrabar_exit
from app.backtest.execution import limit_touched, serialize_events
from app.backtest.execution import OrderEvent as SimOrderEvent
from app.backtest.video_strategies import Order, VideoConfig
from app.models.instrument import Instrument
from app.services.futures_math import contracts_for_risk, risk_dollars


class OrderLifecycle(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partially_filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass
class PendingVideoOrder:
    order: Order
    qty: int
    state: OrderLifecycle = OrderLifecycle.PENDING
    events: list[SimOrderEvent] = field(default_factory=list)

    def log(self, ts, event: str, detail: str, price: Decimal | None = None) -> None:
        self.events.append(SimOrderEvent(ts=ts, event=event, detail=detail, price=price))


@dataclass
class SimulationStats:
    orders_placed: int = 0
    orders_filled: int = 0
    orders_expired: int = 0
    orders_rejected: int = 0
    orders_cancelled: int = 0

    def fill_rate(self) -> float | None:
        if self.orders_placed == 0:
            return None
        return self.orders_filled / self.orders_placed


def _position_size(o: Order, cfg: VideoConfig, instrument: Instrument) -> int:
    slip_buf = risk_dollars(cfg.tick * Decimal(cfg.slippage_ticks * 2), instrument)
    comm = cfg.commission_side * Decimal(2)
    budget = cfg.risk_dollars - slip_buf - comm
    if budget <= 0:
        return 0
    qty = contracts_for_risk(o.limit, o.stop, budget, instrument)
    return min(cfg.max_contracts, max(0, qty))


def _mae_mfe(direction: str, entry: Decimal, qty: int, instrument: Instrument, bars: list[Bar], i0: int, i1: int):
    mae = Decimal(0)
    mfe = Decimal(0)
    mult = instrument.multiplier
    for j in range(i0, i1 + 1):
        b = bars[j]
        if direction == "long":
            mfe = max(mfe, max(Decimal(0), (b.high - entry) * mult * qty))
            mae = max(mae, max(Decimal(0), (entry - b.low) * mult * qty))
        else:
            mfe = max(mfe, max(Decimal(0), (entry - b.low) * mult * qty))
            mae = max(mae, max(Decimal(0), (b.high - entry) * mult * qty))
    return mae, mfe


def run_video_orders(
    bars: list[Bar],
    orders: list[Order],
    cfg: VideoConfig,
    instrument: Instrument,
) -> tuple[list[dict], SimulationStats, dict[str, Any]]:
    ledger: list[dict] = []
    stats = SimulationStats()
    busy_until = -1
    tick = cfg.tick
    slip = cfg.slippage_ticks

    for o in sorted(orders, key=lambda x: (x.signal_index, x.strategy)):
        valid_long = o.stop < o.limit < o.target
        valid_short = o.target < o.limit < o.stop
        if not (valid_long if o.direction == "long" else valid_short):
            stats.orders_rejected += 1
            continue

        qty = _position_size(o, cfg, instrument)
        if qty < 1:
            stats.orders_rejected += 1
            continue

        stats.orders_placed += 1
        pending = PendingVideoOrder(order=o, qty=qty)
        pending.log(bars[o.signal_index].ts, "placed", f"limit {o.limit} qty {qty}", o.limit)

        fill_idx: int | None = None
        last_try = min(o.expiry_index, len(bars) - 1)
        for j in range(o.signal_index + 1, last_try + 1):
            if j <= busy_until:
                pending.state = OrderLifecycle.CANCELLED
                pending.log(bars[j].ts, "cancelled", "position conflict — another trade open")
                stats.orders_cancelled += 1
                fill_idx = None
                break
            b = bars[j]
            if limit_touched(o.direction, o.limit, b):
                pending.state = OrderLifecycle.FILLED
                pending.log(
                    bars[j].ts,
                    "filled",
                    "limit touch (OHLC eligibility — not a live fill guarantee)",
                    o.limit,
                )
                fill_idx = j
                stats.orders_filled += 1
                break
        if fill_idx is None and pending.state == OrderLifecycle.PENDING:
            pending.state = OrderLifecycle.EXPIRED
            pending.log(bars[last_try].ts, "expired", "limit not touched before expiry")
            stats.orders_expired += 1

        if fill_idx is None:
            continue

        ref_entry = o.limit
        exec_entry = apply_slippage(ref_entry, o.direction, "entry", tick, slip)
        planned_risk = risk_dollars(abs(ref_entry - o.stop), instrument) * qty

        ref_exit = ref_entry
        exec_exit = exec_entry
        exit_reason = "end_of_data"
        exit_idx = len(bars) - 1

        for j in range(fill_idx + 1, len(bars)):
            b = bars[j]
            hit_px, hit_reason = check_intrabar_exit(o.direction, o.stop, o.target, b)
            if hit_px is not None and hit_reason is not None:
                ref_exit = hit_px
                exec_exit = apply_slippage(ref_exit, o.direction, "exit", tick, slip)
                exit_reason = "stop" if "stop" in hit_reason else "target"
                if "gap" in hit_reason:
                    exit_reason = "stop_gap"
                exit_idx = j
                break

        if exit_reason == "end_of_data":
            ref_exit = bars[-1].close
            exec_exit = apply_slippage(ref_exit, o.direction, "exit", tick, slip)

        settlement = settle_trade(
            direction=o.direction,
            qty=qty,
            instrument=instrument,
            ref_entry=ref_entry,
            exec_entry=exec_entry,
            ref_exit=ref_exit,
            exec_exit=exec_exit,
            commission_per_side=cfg.commission_side,
        )
        mae, mfe = _mae_mfe(o.direction, exec_entry, qty, instrument, bars, fill_idx, exit_idx)
        realized_risk = Decimal(0)
        if exit_reason.startswith("stop"):
            realized_risk = max(Decimal(0), -settlement.net_pnl)

        duration_bars = exit_idx - fill_idx
        ledger.append(
            {
                "trade_number": len(ledger) + 1,
                "direction": o.direction,
                "quantity": qty,
                "signal_ts": bars[o.signal_index].ts,
                "entry_ts": bars[fill_idx].ts,
                "entry_price": exec_entry,
                "exit_ts": bars[exit_idx].ts,
                "exit_price": exec_exit,
                "stop_price": o.stop,
                "target_price": o.target,
                "exit_reason": exit_reason,
                "gross_pnl": settlement.gross_pnl,
                "commissions": settlement.commissions,
                "slippage": settlement.slippage,
                "net_pnl": settlement.net_pnl,
                "mae": mae,
                "mfe": mfe,
                "planned_risk_dollars": planned_risk,
                "realized_loss_dollars": realized_risk,
                "duration_bars": duration_bars,
                "meta": {
                    "signal_reason": o.reason,
                    "strategy": o.strategy,
                    "entry_mode": "limit",
                    "limit_price": str(o.limit),
                    "reference_entry": str(ref_entry),
                    "reference_exit": str(ref_exit),
                    "order_state": pending.state.value,
                    "ohlc_assumptions": [
                        "limit_touch_eligible_not_guaranteed",
                        "entry_bar_skips_exit",
                        "stop_before_target",
                    ],
                    "order_events": serialize_events(pending.events),
                },
            }
        )
        busy_until = exit_idx

    analytics = _aggregate_analytics(ledger, stats, bars)
    return ledger, stats, analytics


def _aggregate_analytics(trades: list[dict], stats: SimulationStats, bars: list[Bar]) -> dict[str, Any]:
    if not trades:
        return {
            "entry_fill_rate": stats.fill_rate(),
            "orders_placed": stats.orders_placed,
            "orders_filled": stats.orders_filled,
            "orders_expired": stats.orders_expired,
            "orders_rejected": stats.orders_rejected,
            "orders_cancelled": stats.orders_cancelled,
            "avg_trade_duration_bars": None,
            "max_daily_loss": None,
        }
    durations = [int(t["duration_bars"]) for t in trades]
    daily: dict[str, Decimal] = {}
    for t in trades:
        day = t["exit_ts"].date().isoformat()
        daily[day] = daily.get(day, Decimal(0)) + t["net_pnl"]
    max_daily_loss = float(min(daily.values())) if daily else None
    return {
        "entry_fill_rate": stats.fill_rate(),
        "orders_placed": stats.orders_placed,
        "orders_filled": stats.orders_filled,
        "orders_expired": stats.orders_expired,
        "orders_rejected": stats.orders_rejected,
        "orders_cancelled": stats.orders_cancelled,
        "avg_trade_duration_bars": sum(durations) / len(durations),
        "max_daily_loss": max_daily_loss,
        "cancellation_rate": (stats.orders_cancelled / stats.orders_placed) if stats.orders_placed else None,
    }