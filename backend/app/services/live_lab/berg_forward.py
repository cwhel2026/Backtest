"""Incremental Berg TNB forward runner — one bar per step, persisted runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from app.backtest.bars import Bar
from app.backtest.berg_tnb.pipeline import BergTnbEngine
from app.backtest.video_strategies import Order


@dataclass
class BergForwardRuntime:
    """Persistent forward-test state for Berg TNB (versioned)."""

    version: int = 1
    last_bar_index: int = -1
    last_snapshot: dict[str, Any] = field(default_factory=dict)
    placed_order_keys: list[str] = field(default_factory=list)
    bars_4h_last_ts: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict | None) -> BergForwardRuntime:
        if not raw:
            return cls()
        return cls(
            version=int(raw.get("version", 1)),
            last_bar_index=int(raw.get("last_bar_index", -1)),
            last_snapshot=dict(raw.get("last_snapshot") or {}),
            placed_order_keys=list(raw.get("placed_order_keys") or []),
            bars_4h_last_ts=raw.get("bars_4h_last_ts"),
        )


def _order_key(order: Order) -> str:
    return f"{order.signal_index}:{order.limit}:{order.direction}"


def berg_forward_step(
    runtime: BergForwardRuntime,
    spec: dict,
    bars_5m: list[Bar],
    bars_4h: list[Bar],
    tick: Decimal,
) -> tuple[BergForwardRuntime, list[Order], dict[int, dict]]:
    """Process exactly the latest 5m bar once; requires closed 4H context already in store."""
    bar_index = len(bars_5m) - 1
    if bar_index < 0:
        return runtime, [], {}
    if bar_index <= runtime.last_bar_index:
        return runtime, [], {}

    if len(bars_4h) < 3:
        return runtime, [], {}

    if bars_4h:
        runtime.bars_4h_last_ts = bars_4h[-1].ts.isoformat()

    spec_fwd = {**spec, "forward_test": True}
    engine = BergTnbEngine(spec_fwd, bars_5m, tick)
    _setups, orders, _events, _rej = engine.run()
    snapshots = getattr(engine, "_forward_snapshots", {})

    new_orders: list[Order] = []
    for order in orders:
        if order.signal_index != bar_index:
            continue
        key = _order_key(order)
        if key in runtime.placed_order_keys:
            continue
        runtime.placed_order_keys.append(key)
        new_orders.append(order)

    runtime.last_bar_index = bar_index
    runtime.last_snapshot = snapshots.get(bar_index) or runtime.last_snapshot
    return runtime, new_orders, snapshots