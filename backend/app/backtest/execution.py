"""Simulated order queue — signals do not fill until price proves reachability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from app.backtest.bars import Bar
from app.backtest.costs import round_to_tick


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


@dataclass
class OrderEvent:
    ts: datetime
    event: str
    detail: str
    price: Decimal | None = None


@dataclass
class SimulatedOrder:
    order_id: int
    direction: str  # long | short (position to open)
    order_type: OrderType
    limit_or_stop_price: Decimal
    qty: int
    created_ts: datetime
    expire_ts: datetime | None
    stop_price: Decimal
    target_price: Decimal
    reason: str
    events: list[OrderEvent] = field(default_factory=list)
    invalidated: bool = False

    def log(self, ts: datetime, event: str, detail: str, price: Decimal | None = None) -> None:
        self.events.append(OrderEvent(ts=ts, event=event, detail=detail, price=price))


def _side_for_entry(direction: str, order_type: OrderType) -> OrderSide:
    if order_type == OrderType.MARKET:
        return OrderSide.BUY if direction == "long" else OrderSide.SELL
    if order_type == OrderType.LIMIT:
        return OrderSide.BUY if direction == "long" else OrderSide.SELL
    return OrderSide.BUY if direction == "long" else OrderSide.SELL


def validate_order(order: SimulatedOrder, tick: Decimal) -> list[str]:
    errors: list[str] = []
    if order.qty < 1:
        errors.append("quantity must be >= 1")
    if tick <= 0:
        errors.append("invalid tick size")
    if order.order_type == OrderType.LIMIT:
        rounded = round_to_tick(order.limit_or_stop_price, tick)
        if rounded != order.limit_or_stop_price:
            errors.append("limit price must align to tick size")
    if order.direction == "long" and order.stop_price >= order.limit_or_stop_price and order.order_type == OrderType.LIMIT:
        errors.append("long limit must be above stop")
    if order.direction == "short" and order.stop_price <= order.limit_or_stop_price and order.order_type == OrderType.LIMIT:
        errors.append("short limit must be below stop")
    return errors


def limit_touched(direction: str, limit: Decimal, bar: Bar) -> bool:
    """True if OHLCV shows the limit could have traded (no invented intrabar path)."""
    if direction == "long":
        return bar.low <= limit
    return bar.high >= limit


def stop_entry_touched(direction: str, stop: Decimal, bar: Bar) -> bool:
    if direction == "long":
        return bar.high >= stop
    return bar.low <= stop


def fill_limit(direction: str, limit: Decimal, bar: Bar, tick: Decimal) -> Decimal | None:
    if not limit_touched(direction, limit, bar):
        return None
    return round_to_tick(limit, tick)


def fill_market_open(direction: str, bar: Bar, tick: Decimal) -> Decimal:
    return round_to_tick(bar.open, tick)


def process_order_bar(order: SimulatedOrder, bar: Bar, tick: Decimal) -> Decimal | None:
    """Return fill price if the order completes on this bar."""
    if order.invalidated:
        return None
    if order.expire_ts is not None and bar.ts > order.expire_ts:
        order.log(bar.ts, "expired", "order expired")
        order.invalidated = True
        return None
    if order.order_type == OrderType.MARKET:
        px = fill_market_open(order.direction, bar, tick)
        order.log(bar.ts, "filled", "market at bar open", px)
        return px
    if order.order_type == OrderType.LIMIT:
        px = fill_limit(order.direction, order.limit_or_stop_price, bar, tick)
        if px is not None:
            order.log(bar.ts, "filled", "limit touched", px)
        return px
    if order.order_type == OrderType.STOP:
        if stop_entry_touched(order.direction, order.limit_or_stop_price, bar):
            px = round_to_tick(order.limit_or_stop_price, tick)
            order.log(bar.ts, "filled", "stop entry touched", px)
            return px
    return None


def serialize_events(events: list[OrderEvent]) -> list[dict[str, Any]]:
    return [
        {
            "ts": e.ts.isoformat(),
            "event": e.event,
            "detail": e.detail,
            "price": float(e.price) if e.price is not None else None,
        }
        for e in events
    ]