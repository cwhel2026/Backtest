"""Chronological OHLC order-state simulator for video strategies and Berg limits.

Processing order on each bar j (pending):
1. Apply amendments with amendment.bar_index == j (bar open).
2. Evaluate fill using prices effective at j (no retroactive use of future amendments).
3. No amendments after fill.

Exit on fill bar governed by EntryBarExitPolicy (default conservative_ohlc).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from app.backtest.bars import Bar
from app.backtest.costs import apply_slippage, settle_trade
from app.backtest.exits import check_intrabar_exit
from app.backtest.execution import limit_touched, serialize_events
from app.backtest.execution import OrderEvent as SimOrderEvent
from app.backtest.ohlc_policies import (
    EntryBarExitPolicy,
    ExitEvaluation,
    PendingFillPolicy,
    evaluate_fill_bar_exit,
    pending_limit_fill_eligible,
)
from app.backtest.video_strategies import Order, VideoConfig, effective_order_prices
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
    limit, stop, _ = effective_order_prices(o, o.signal_index)
    slip_buf = risk_dollars(cfg.tick * Decimal(cfg.slippage_ticks * 2), instrument)
    comm = cfg.commission_side * Decimal(2)
    budget = cfg.risk_dollars - slip_buf - comm
    if budget <= 0:
        return 0
    qty = contracts_for_risk(limit, stop, budget, instrument)
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


def _parse_entry_bar_policy(cfg: VideoConfig) -> EntryBarExitPolicy:
    raw = (cfg.entry_bar_exit_policy or "conservative_ohlc").lower()
    if raw == "skip_exits":
        return EntryBarExitPolicy.SKIP_EXITS
    return EntryBarExitPolicy.CONSERVATIVE_OHLC


def _parse_pending_fill_policy(cfg: VideoConfig) -> PendingFillPolicy:
    raw = (cfg.pending_fill_policy or "no_fill_if_stop_touched").lower()
    if raw == "allow_fill_then_exit":
        return PendingFillPolicy.ALLOW_FILL_THEN_EXIT
    return PendingFillPolicy.NO_FILL_IF_STOP_TOUCHED


def _valid_bracket(direction: str, limit: Decimal, stop: Decimal, target: Decimal) -> bool:
    valid_long = stop < limit < target
    valid_short = target < limit < stop
    return valid_long if direction == "long" else valid_short


def _simulate_one_order(
    bars: list[Bar],
    order: Order,
    cfg: VideoConfig,
    instrument: Instrument,
    *,
    busy_until: int,
    entry_policy: EntryBarExitPolicy,
    fill_policy: PendingFillPolicy,
) -> tuple[dict | None, PendingVideoOrder, int, list[str]]:
    """Return trade ledger row, pending state, new busy_until, uncertainties."""
    tick = cfg.tick
    slip = cfg.slippage_ticks
    pending = PendingVideoOrder(order=order, qty=0)
    uncertainties: list[str] = []
    last_try = min(order.expiry_index, len(bars) - 1)

    limit0, stop0, target0 = effective_order_prices(order, order.signal_index)
    if not _valid_bracket(order.direction, limit0, stop0, target0):
        pending.state = OrderLifecycle.REJECTED
        return None, pending, busy_until, ["invalid_bracket_at_submit"]

    qty = _position_size(order, cfg, instrument)
    if qty < 1:
        pending.state = OrderLifecycle.REJECTED
        return None, pending, busy_until, ["insufficient_size_for_risk"]

    pending.qty = qty
    pending.log(bars[order.signal_index].ts, "placed", f"limit {limit0} qty {qty}", limit0)

    fill_idx: int | None = None
    fill_limit = fill_stop = fill_target = limit0

    for j in range(order.signal_index + 1, last_try + 1):
        if j <= busy_until:
            pending.state = OrderLifecycle.CANCELLED
            pending.log(bars[j].ts, "cancelled", "position conflict — another trade open")
            return None, pending, busy_until, uncertainties

        for amend in order.amendments:
            if amend.bar_index == j:
                lim, stp, tgt = amend.limit, amend.stop, amend.target
                if not _valid_bracket(order.direction, lim, stp, tgt):
                    pending.log(bars[j].ts, "cancelled", "amendment produced invalid bracket")
                    pending.state = OrderLifecycle.CANCELLED
                    return None, pending, busy_until, uncertainties + ["invalid_amendment_bracket"]
                pending.log(
                    bars[j].ts,
                    "amended",
                    f"limit {lim} stop {stp} target {tgt} (effective bar open)",
                    lim,
                )
        limit_j, stop_j, target_j = effective_order_prices(order, j)

        eligible, u_tags = pending_limit_fill_eligible(
            order.direction, limit_j, stop_j, bars[j], fill_policy
        )
        uncertainties.extend(u_tags)
        if eligible and limit_touched(order.direction, limit_j, bars[j]):
            pending.state = OrderLifecycle.FILLED
            pending.log(
                bars[j].ts,
                "filled",
                "limit touch (OHLC eligibility — not a live fill guarantee)",
                limit_j,
            )
            fill_idx = j
            fill_limit, fill_stop, fill_target = limit_j, stop_j, target_j
            break

    if fill_idx is None:
        if pending.state == OrderLifecycle.PENDING:
            pending.state = OrderLifecycle.EXPIRED
            pending.log(bars[last_try].ts, "expired", "limit not touched before expiry")
        return None, pending, busy_until, uncertainties

    ref_entry = fill_limit
    exec_entry = apply_slippage(ref_entry, order.direction, "entry", tick, slip)
    planned_risk = risk_dollars(abs(ref_entry - fill_stop), instrument) * qty

    ref_exit = ref_entry
    exec_exit = exec_entry
    exit_reason = "end_of_data"
    exit_idx = len(bars) - 1

    fill_bar_eval: ExitEvaluation | None = None
    if entry_policy == EntryBarExitPolicy.CONSERVATIVE_OHLC:
        fill_bar_eval = evaluate_fill_bar_exit(
            order.direction, fill_stop, fill_target, bars[fill_idx], entry_policy
        )
        if fill_bar_eval:
            uncertainties.extend(fill_bar_eval.uncertainties)

    if fill_bar_eval and fill_bar_eval.price is not None and fill_bar_eval.reason:
        ref_exit = fill_bar_eval.price
        exec_exit = apply_slippage(ref_exit, order.direction, "exit", tick, slip)
        exit_reason = fill_bar_eval.reason
        exit_idx = fill_idx
    else:
        # SKIP_EXITS and conservative fill-bar miss: no exit on the fill bar (OHLC cannot prove intrabar order).
        start_exit = fill_idx + 1
        for j in range(start_exit, len(bars)):
            b = bars[j]
            hit_px, hit_reason = check_intrabar_exit(order.direction, fill_stop, fill_target, b)
            if hit_px is not None and hit_reason is not None:
                if order.direction == "long":
                    if b.low <= fill_stop and b.high >= fill_target:
                        uncertainties.append("exit_bar_stop_and_target_same_bar_stop_first")
                else:
                    if b.high >= fill_stop and b.low <= fill_target:
                        uncertainties.append("exit_bar_stop_and_target_same_bar_stop_first")
                ref_exit = hit_px
                exec_exit = apply_slippage(ref_exit, order.direction, "exit", tick, slip)
                exit_reason = "stop" if "stop" in hit_reason else "target"
                if "gap" in hit_reason:
                    exit_reason = "stop_gap"
                exit_idx = j
                break

    if exit_reason == "end_of_data":
        ref_exit = bars[-1].close
        exec_exit = apply_slippage(ref_exit, order.direction, "exit", tick, slip)

    settlement = settle_trade(
        direction=order.direction,
        qty=qty,
        instrument=instrument,
        ref_entry=ref_entry,
        exec_entry=exec_entry,
        ref_exit=ref_exit,
        exec_exit=exec_exit,
        commission_per_side=cfg.commission_side,
    )
    mae, mfe = _mae_mfe(order.direction, exec_entry, qty, instrument, bars, fill_idx, exit_idx)
    realized_risk = Decimal(0)
    if exit_reason.startswith("stop"):
        realized_risk = max(Decimal(0), -settlement.net_pnl)

    duration_bars = exit_idx - fill_idx
    trade = {
        "trade_number": 0,
        "direction": order.direction,
        "quantity": qty,
        "signal_ts": bars[order.signal_index].ts,
        "entry_ts": bars[fill_idx].ts,
        "entry_price": exec_entry,
        "exit_ts": bars[exit_idx].ts,
        "exit_price": exec_exit,
        "stop_price": fill_stop,
        "target_price": fill_target,
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
            "signal_reason": order.reason,
            "strategy": order.strategy,
            "setup_id": order.setup_id,
            "entry_mode": "limit",
            "limit_price": str(fill_limit),
            "reference_entry": str(ref_entry),
            "reference_exit": str(ref_exit),
            "order_state": pending.state.value,
            "entry_bar_exit_policy": entry_policy.value,
            "pending_fill_policy": fill_policy.value,
            "ohlc_assumptions": [
                "limit_touch_eligible_not_guaranteed",
                "amendments_effective_at_bar_open",
                "no_amend_after_fill",
                "stop_before_target_on_ambiguous_bar",
            ],
            "execution_uncertainties": uncertainties,
            "order_events": serialize_events(pending.events),
        },
    }
    return trade, pending, exit_idx, uncertainties


def run_video_orders(
    bars: list[Bar],
    orders: list[Order],
    cfg: VideoConfig,
    instrument: Instrument,
) -> tuple[list[dict], SimulationStats, dict[str, Any]]:
    ledger: list[dict] = []
    stats = SimulationStats()
    busy_until = -1
    entry_policy = _parse_entry_bar_policy(cfg)
    fill_policy = _parse_pending_fill_policy(cfg)

    for o in sorted(orders, key=lambda x: (x.signal_index, x.strategy)):
        limit0, stop0, target0 = effective_order_prices(o, o.signal_index)
        if not _valid_bracket(o.direction, limit0, stop0, target0):
            stats.orders_rejected += 1
            continue

        qty_probe = _position_size(o, cfg, instrument)
        if qty_probe < 1:
            stats.orders_rejected += 1
            continue

        stats.orders_placed += 1
        trade, pending, new_busy, _ = _simulate_one_order(
            bars,
            o,
            cfg,
            instrument,
            busy_until=busy_until,
            entry_policy=entry_policy,
            fill_policy=fill_policy,
        )

        if trade is None:
            if pending.state == OrderLifecycle.EXPIRED:
                stats.orders_expired += 1
            elif pending.state == OrderLifecycle.CANCELLED:
                stats.orders_cancelled += 1
            elif pending.state == OrderLifecycle.REJECTED:
                stats.orders_rejected += 1
            continue

        stats.orders_filled += 1
        trade["trade_number"] = len(ledger) + 1
        ledger.append(trade)
        busy_until = new_busy

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