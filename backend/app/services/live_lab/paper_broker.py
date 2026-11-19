"""Event-driven simulated paper broker — not a real broker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.bars import Bar
from app.backtest.costs import apply_slippage, settle_trade
from app.models.enums import PaperOrderState
from app.models.instrument import Instrument
from app.models.live_lab import PaperBrokerOrder
from app.services.live_lab.ledger import append_ledger_event
from app.services.live_lab.types import MarketEvent


@dataclass
class FillResult:
    order_id: UUID
    filled_qty: int
    fill_price: Decimal
    uncertainty_tags: list[str]
    net_pnl: Decimal | None = None


class PaperBroker:
    """Conservative fills: limits require trade through price; stops use touch with slippage tag."""

    def __init__(self, session: Session, run_id: UUID, instrument: Instrument, slip_ticks: int = 1):
        self.session = session
        self.run_id = run_id
        self.instrument = instrument
        self.slip_ticks = slip_ticks

    def create_order(
        self,
        *,
        side: str,
        order_type: str,
        qty: int,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
        exchange_ts: datetime | None,
        server_ts: datetime,
        client_order_id: str | None = None,
    ) -> PaperBrokerOrder:
        cid = client_order_id or str(uuid4())
        order = PaperBrokerOrder(
            run_id=self.run_id,
            client_order_id=cid,
            state=PaperOrderState.CREATED,
            side=side.lower(),
            order_type=order_type.lower(),
            quantity=qty,
            limit_price=limit_price,
            stop_price=stop_price,
            exchange_ts=exchange_ts,
            server_received_ts=server_ts,
        )
        self.session.add(order)
        self.session.flush()
        append_ledger_event(
            self.session,
            run_id=self.run_id,
            event_type="order_created",
            idempotency_key=f"order:{cid}",
            payload={"client_order_id": cid, "side": side, "type": order_type, "qty": qty},
            exchange_ts=exchange_ts,
            server_received_ts=server_ts,
        )
        order.state = PaperOrderState.SUBMITTED
        order.state = PaperOrderState.ACKNOWLEDGED
        return order

    def process_bar(self, bar: Bar, decision_ts: datetime) -> list[FillResult]:
        fills: list[FillResult] = []
        tick = self.instrument.tick_size
        orders = (
            self.session.execute(
                select(PaperBrokerOrder).where(
                    PaperBrokerOrder.run_id == self.run_id,
                    PaperBrokerOrder.state.in_(
                        (
                            PaperOrderState.ACKNOWLEDGED,
                            PaperOrderState.SUBMITTED,
                            PaperOrderState.PARTIALLY_FILLED,
                        )
                    ),
                )
            )
            .scalars()
            .all()
        )
        for order in orders:
            result = self._try_fill(order, bar, tick, decision_ts)
            if result:
                fills.append(result)
        return fills

    def _try_fill(
        self, order: PaperBrokerOrder, bar: Bar, tick: Decimal, decision_ts: datetime
    ) -> FillResult | None:
        tags: list[str] = []
        fill_px: Decimal | None = None
        if order.order_type == "market":
            direction = "long" if order.side == "buy" else "short"
            fill_px = apply_slippage(bar.open, direction, "entry", tick, self.slip_ticks)
            tags.append("market_slippage")
            tags.append("ohlc_open_proxy")
        elif order.order_type == "limit" and order.limit_price is not None:
            if order.side == "buy" and bar.low <= order.limit_price:
                if bar.open <= order.limit_price:
                    fill_px = bar.open
                    tags.append("limit_filled_open")
                else:
                    fill_px = order.limit_price
                    tags.append("limit_touch_not_queue_priority")
            elif order.side == "sell" and bar.high >= order.limit_price:
                if bar.open >= order.limit_price:
                    fill_px = bar.open
                    tags.append("limit_filled_open")
                else:
                    fill_px = order.limit_price
                    tags.append("limit_touch_not_queue_priority")
        elif order.order_type == "stop" and order.stop_price is not None:
            if order.side == "sell" and bar.low <= order.stop_price:
                fill_px = apply_slippage(order.stop_price, order.side, "exit", tick, self.slip_ticks)
                tags.append("stop_touch_slippage")
            elif order.side == "buy" and bar.high >= order.stop_price:
                fill_px = apply_slippage(order.stop_price, order.side, "entry", tick, self.slip_ticks)
                tags.append("stop_touch_slippage")
        if fill_px is None:
            return None
        order.filled_qty = order.quantity
        order.avg_fill_price = fill_px
        order.state = PaperOrderState.FILLED
        order.uncertainty_tags = tags
        order.updated_at = datetime.now(UTC)
        append_ledger_event(
            self.session,
            run_id=self.run_id,
            event_type="order_filled",
            idempotency_key=f"fill:{order.client_order_id}:{bar.ts.isoformat()}",
            payload={
                "client_order_id": order.client_order_id,
                "fill_price": str(fill_px),
                "tags": tags,
            },
            exchange_ts=bar.ts,
            server_received_ts=datetime.now(UTC),
            decision_ts=decision_ts,
        )
        return FillResult(getattr(order, "id", None) or uuid4(), order.quantity, fill_px, tags)

    def close_position_market(
        self,
        *,
        direction: str,
        qty: int,
        ref_entry: Decimal,
        exec_entry: Decimal,
        bar: Bar,
        decision_ts: datetime,
    ) -> FillResult:
        exit_side = "sell" if direction == "long" else "buy"
        tick = self.instrument.tick_size
        raw_exit = bar.close
        exec_exit = apply_slippage(raw_exit, exit_side, "exit", tick, self.slip_ticks)
        settlement = settle_trade(
            direction=direction,
            qty=qty,
            instrument=self.instrument,
            ref_entry=ref_entry,
            exec_entry=exec_entry,
            ref_exit=raw_exit,
            exec_exit=exec_exit,
            commission_per_side=self.instrument.default_commission_per_side,
        )
        append_ledger_event(
            self.session,
            run_id=self.run_id,
            event_type="position_closed",
            idempotency_key=f"close:{direction}:{bar.ts.isoformat()}",
            payload={"net_pnl": str(settlement.net_pnl), "exit": str(exec_exit)},
            exchange_ts=bar.ts,
            decision_ts=decision_ts,
        )
        return FillResult(
            uuid4(),
            qty,
            exec_exit,
            ["bar_close_exit", "market_slippage"],
            net_pnl=settlement.net_pnl,
        )