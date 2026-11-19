"""Chronological incremental video-order execution for forward tests."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.backtest.bars import Bar
from app.backtest.costs import apply_slippage, settle_trade
from app.backtest.exits import check_intrabar_exit
from app.backtest.execution import limit_touched, serialize_events
from app.backtest.ohlc_policies import (
    EntryBarExitPolicy,
    evaluate_fill_bar_exit,
    pending_limit_fill_eligible,
)
from app.backtest.video_execution import (
    OrderLifecycle,
    PendingVideoOrder,
    SimulationStats,
    _parse_entry_bar_policy,
    _parse_pending_fill_policy,
    _position_size,
    _valid_bracket,
)
from app.backtest.video_strategies import Order, VideoConfig, effective_order_prices
from app.models.instrument import Instrument


@dataclass
class OpenForwardPosition:
    direction: str
    qty: int
    fill_idx: int
    fill_limit: Decimal
    fill_stop: Decimal
    fill_target: Decimal
    exec_entry: Decimal
    ref_entry: Decimal
    order: Order
    pending_events: list
    uncertainties: list[str] = field(default_factory=list)
    entry_policy: str = "conservative_ohlc"
    fill_policy: str = "no_fill_if_stop_touched"


@dataclass
class ForwardExecutorState:
    version: int = 2
    last_bar_ts: str | None = None
    bars_count: int = 0
    busy_until: int = -1
    pending: list[dict] = field(default_factory=list)
    open_position: dict | None = None
    placed_setup_keys: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


@dataclass
class ForwardStepResult:
    events: list[dict]
    trade_closed: dict | None = None
    net_pnl: Decimal | None = None


def _serialize_pending(pv: PendingVideoOrder) -> dict:
    o = pv.order
    return {
        "state": pv.state.value,
        "qty": pv.qty,
        "next_eval_index": getattr(pv, "_next_eval_index", o.signal_index + 1),
        "order": {
            "strategy": o.strategy,
            "direction": o.direction,
            "signal_index": o.signal_index,
            "limit": str(o.limit),
            "stop": str(o.stop),
            "target": str(o.target),
            "expiry_index": o.expiry_index,
            "reason": o.reason,
            "setup_id": o.setup_id,
            "amendments": [
                {
                    "bar_index": a.bar_index,
                    "limit": str(a.limit),
                    "stop": str(a.stop),
                    "target": str(a.target),
                }
                for a in o.amendments
            ],
        },
        "events": serialize_events(pv.events),
        "uncertainties": getattr(pv, "_uncertainties", []),
    }


def _deserialize_pending(raw: dict) -> PendingVideoOrder:
    od = raw["order"]
    order = Order(
        od["strategy"],
        od["direction"],
        od["signal_index"],
        Decimal(od["limit"]),
        Decimal(od["stop"]),
        Decimal(od["target"]),
        od["expiry_index"],
        od["reason"],
        setup_id=od.get("setup_id"),
        amendments=[],
    )
    from app.backtest.video_strategies import OrderAmendment

    for a in od.get("amendments") or []:
        order.amendments.append(
            OrderAmendment(
                a["bar_index"],
                Decimal(a["limit"]),
                Decimal(a["stop"]),
                Decimal(a["target"]),
            )
        )
    pv = PendingVideoOrder(order=order, qty=int(raw.get("qty") or 0))
    pv.state = OrderLifecycle(raw.get("state", "pending"))
    pv._next_eval_index = int(raw.get("next_eval_index", order.signal_index + 1))  # noqa: SLF001
    pv._uncertainties = list(raw.get("uncertainties") or [])  # noqa: SLF001
    return pv


class IncrementalVideoForwardEngine:
    """Advance one closed bar at a time; never re-simulate completed trades."""

    def __init__(
        self,
        state: ForwardExecutorState | None,
        cfg: VideoConfig,
        instrument: Instrument,
    ):
        self.cfg = cfg
        self.instrument = instrument
        self.state = state or ForwardExecutorState()
        self.entry_policy = _parse_entry_bar_policy(cfg)
        self.fill_policy = _parse_pending_fill_policy(cfg)
        self.tick = cfg.tick
        self.slip = cfg.slippage_ticks
        self.stats = SimulationStats()

    def load_pending(self) -> list[PendingVideoOrder]:
        return [_deserialize_pending(p) for p in self.state.pending]

    def save_pending(self, items: list[PendingVideoOrder]) -> None:
        self.state.pending = [_serialize_pending(p) for p in items if p.state == OrderLifecycle.PENDING]

    def submit_order(self, order: Order, bars: list[Bar]) -> list[dict]:
        events: list[dict] = []
        key = f"{order.signal_index}:{order.limit}:{order.direction}"
        if key in self.state.placed_setup_keys:
            return events
        limit0, stop0, target0 = effective_order_prices(order, order.signal_index)
        if not _valid_bracket(order.direction, limit0, stop0, target0):
            events.append({"type": "order_rejected", "reason": "invalid_bracket", "setup_id": key})
            return events
        qty = _position_size(order, self.cfg, self.instrument)
        if qty < 1:
            events.append({"type": "order_rejected", "reason": "size", "setup_id": key})
            return events
        pv = PendingVideoOrder(order=order, qty=qty)
        pv._next_eval_index = order.signal_index + 1  # noqa: SLF001
        pv._uncertainties = []  # noqa: SLF001
        pv.log(bars[order.signal_index].ts, "placed", f"limit {limit0} qty {qty}", limit0)
        pending = self.load_pending()
        pending.append(pv)
        self.save_pending(pending)
        self.state.placed_setup_keys.append(key)
        self.stats.orders_placed += 1
        events.append(
            {
                "type": "order_placed",
                "setup_id": key,
                "signal_index": order.signal_index,
                "limit": str(limit0),
                "qty": qty,
            }
        )
        return events

    def on_bar(self, bars: list[Bar], bar_index: int) -> ForwardStepResult:
        """Process exactly one new bar close at bar_index."""
        out_events: list[dict] = []
        if self.state.open_position:
            closed = self._advance_open_position(bars, bar_index)
            if closed:
                out_events.append({"type": "trade_closed", **closed})
                return ForwardStepResult(out_events, trade_closed=closed["trade"], net_pnl=Decimal(str(closed["net_pnl"])))
            return ForwardStepResult(out_events)

        pending_list = self.load_pending()
        still: list[PendingVideoOrder] = []
        for pv in pending_list:
            if pv.state != OrderLifecycle.PENDING:
                continue
            j = getattr(pv, "_next_eval_index", pv.order.signal_index + 1)
            if j > bar_index:
                still.append(pv)
                continue
            if j != bar_index:
                pv._next_eval_index = j  # noqa: SLF001
                still.append(pv)
                continue
            if j <= self.state.busy_until:
                pv.state = OrderLifecycle.CANCELLED
                pv.log(bars[j].ts, "cancelled", "position conflict")
                out_events.append({"type": "order_cancelled", "reason": "busy", "bar_index": j})
                continue
            for amend in pv.order.amendments:
                if amend.bar_index == j:
                    pv.log(bars[j].ts, "amended", "prices updated at bar open", amend.limit)
                    out_events.append({"type": "order_amended", "bar_index": j, "limit": str(amend.limit)})
            limit_j, stop_j, target_j = effective_order_prices(pv.order, j)
            eligible, u_tags = pending_limit_fill_eligible(pv.order.direction, limit_j, stop_j, bars[j], self.fill_policy)
            pv._uncertainties.extend(u_tags)  # noqa: SLF001
            if eligible and limit_touched(pv.order.direction, limit_j, bars[j]):
                pv.state = OrderLifecycle.FILLED
                pv.log(bars[j].ts, "filled", "limit touch eligible", limit_j)
                self._open_position(pv, bars, j, limit_j, stop_j, target_j)
                self.state.busy_until = j
                self.stats.orders_filled += 1
                out_events.append(
                    {
                        "type": "order_filled",
                        "bar_index": j,
                        "uncertainties": u_tags,
                        "limit": str(limit_j),
                    }
                )
                still.extend(x for x in pending_list if x is not pv and x.state == OrderLifecycle.PENDING)
                self.save_pending(still)
                self.state.bars_count = bar_index + 1
                self.state.last_bar_ts = bars[bar_index].ts.isoformat()
                exit_on_fill = self._maybe_exit_on_fill_bar(bars, j)
                if exit_on_fill:
                    out_events.append({"type": "trade_closed", **exit_on_fill})
                    return ForwardStepResult(
                        out_events,
                        trade_closed=exit_on_fill["trade"],
                        net_pnl=Decimal(str(exit_on_fill["net_pnl"])),
                    )
                return ForwardStepResult(out_events)

            pv._next_eval_index = j + 1  # noqa: SLF001
            last_try = min(pv.order.expiry_index, len(bars) - 1)
            if j >= last_try:
                pv.state = OrderLifecycle.EXPIRED
                pv.log(bars[j].ts, "expired", "limit not touched")
                self.stats.orders_expired += 1
                out_events.append({"type": "order_expired", "bar_index": j})
            else:
                still.append(pv)

        self.save_pending(still)
        self.state.bars_count = bar_index + 1
        self.state.last_bar_ts = bars[bar_index].ts.isoformat()
        return ForwardStepResult(out_events)

    def _open_position(
        self,
        pv: PendingVideoOrder,
        bars: list[Bar],
        fill_idx: int,
        limit: Decimal,
        stop: Decimal,
        target: Decimal,
    ) -> None:
        ref_entry = limit
        exec_entry = apply_slippage(ref_entry, pv.order.direction, "entry", self.tick, self.slip)
        self.state.open_position = {
            "direction": pv.order.direction,
            "qty": pv.qty,
            "fill_idx": fill_idx,
            "fill_limit": str(limit),
            "fill_stop": str(stop),
            "fill_target": str(target),
            "exec_entry": str(exec_entry),
            "ref_entry": str(ref_entry),
            "order": copy.deepcopy(_serialize_pending(pv)["order"]),
            "pending_events": serialize_events(pv.events),
            "uncertainties": list(getattr(pv, "_uncertainties", [])),
        }
        self.state.pending = []

    def _maybe_exit_on_fill_bar(self, bars: list[Bar], fill_idx: int) -> dict | None:
        if not self.state.open_position:
            return None
        if self.entry_policy != EntryBarExitPolicy.CONSERVATIVE_OHLC:
            return None
        pos = self._position_obj()
        eval_res = evaluate_fill_bar_exit(
            pos.direction, Decimal(pos.fill_stop), Decimal(pos.fill_target), bars[fill_idx], self.entry_policy
        )
        if eval_res and eval_res.price is not None and eval_res.reason:
            return self._close_position(bars, fill_idx, eval_res.price, eval_res.reason, eval_res.uncertainties)
        return None

    def _position_obj(self) -> OpenForwardPosition:
        op = self.state.open_position or {}
        od = op["order"]
        order = Order(
            od["strategy"],
            od["direction"],
            od["signal_index"],
            Decimal(od["limit"]),
            Decimal(od["stop"]),
            Decimal(od["target"]),
            od["expiry_index"],
            od["reason"],
            setup_id=od.get("setup_id"),
        )
        return OpenForwardPosition(
            direction=op["direction"],
            qty=op["qty"],
            fill_idx=op["fill_idx"],
            fill_limit=Decimal(op["fill_limit"]),
            fill_stop=Decimal(op["fill_stop"]),
            fill_target=Decimal(op["fill_target"]),
            exec_entry=Decimal(op["exec_entry"]),
            ref_entry=Decimal(op["ref_entry"]),
            order=order,
            pending_events=op.get("pending_events") or [],
            uncertainties=op.get("uncertainties") or [],
        )

    def _advance_open_position(self, bars: list[Bar], bar_index: int) -> dict | None:
        pos = self._position_obj()
        b = bars[bar_index]
        hit_px, hit_reason = check_intrabar_exit(pos.direction, pos.fill_stop, pos.fill_target, b)
        if hit_px is None or hit_reason is None:
            return None
        reason = "stop" if "stop" in hit_reason else "target"
        return self._close_position(bars, bar_index, hit_px, reason, [])

    def _close_position(
        self, bars: list[Bar], exit_idx: int, ref_exit: Decimal, exit_reason: str, extra_unc: list[str]
    ) -> dict:
        pos = self._position_obj()
        exec_exit = apply_slippage(ref_exit, pos.direction, "exit", self.tick, self.slip)
        settlement = settle_trade(
            direction=pos.direction,
            qty=pos.qty,
            instrument=self.instrument,
            ref_entry=pos.ref_entry,
            exec_entry=pos.exec_entry,
            ref_exit=ref_exit,
            exec_exit=exec_exit,
            commission_per_side=self.cfg.commission_side,
        )
        trade = {
            "direction": pos.direction,
            "quantity": pos.qty,
            "signal_ts": bars[pos.order.signal_index].ts,
            "entry_ts": bars[pos.fill_idx].ts,
            "entry_price": pos.exec_entry,
            "exit_ts": bars[exit_idx].ts,
            "exit_price": exec_exit,
            "exit_reason": exit_reason,
            "net_pnl": settlement.net_pnl,
            "meta": {
                "setup_id": pos.order.setup_id,
                "uncertainties": pos.uncertainties + extra_unc,
                "order_events": pos.pending_events,
            },
        }
        self.state.open_position = None
        self.state.busy_until = exit_idx
        return {"trade": trade, "net_pnl": str(settlement.net_pnl), "exit_reason": exit_reason}