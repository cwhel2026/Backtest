"""Incremental Berg TNB forward runner — one closed 5m bar per step."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from app.backtest.bars import Bar
from app.backtest.berg_tnb.pipeline import BergTnbEngine
from app.backtest.video_strategies import Order, OrderAmendment


BERG_FORWARD_SCHEMA = 2


@dataclass
class BergForwardRuntime:
    """Persistent forward-test state for Berg TNB (versioned)."""

    version: int = BERG_FORWARD_SCHEMA
    last_bar_index: int = -1
    last_snapshot: dict[str, Any] = field(default_factory=dict)
    placed_order_keys: list[str] = field(default_factory=list)
    bars_4h_last_ts: str | None = None
    fsm_state: dict[str, Any] = field(default_factory=dict)
    config_hash: str = ""
    pending_amendments: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict | None) -> BergForwardRuntime:
        if not raw:
            return cls()
        ver = int(raw.get("version", 1))
        if ver < 2:
            return cls(
                version=BERG_FORWARD_SCHEMA,
                last_bar_index=int(raw.get("last_bar_index", -1)),
                last_snapshot=dict(raw.get("last_snapshot") or {}),
                placed_order_keys=list(raw.get("placed_order_keys") or []),
                bars_4h_last_ts=raw.get("bars_4h_last_ts"),
            )
        return cls(
            version=BERG_FORWARD_SCHEMA,
            last_bar_index=int(raw.get("last_bar_index", -1)),
            last_snapshot=dict(raw.get("last_snapshot") or {}),
            placed_order_keys=list(raw.get("placed_order_keys") or []),
            bars_4h_last_ts=raw.get("bars_4h_last_ts"),
            fsm_state=dict(raw.get("fsm_state") or {}),
            config_hash=str(raw.get("config_hash") or ""),
            pending_amendments=list(raw.get("pending_amendments") or []),
        )


def _config_hash(spec: dict) -> str:
    entry = spec.get("entry") or {}
    payload = json.dumps(
        {k: spec.get(k) for k in ("instrument_symbol", "timeframe", "exit", "risk", "exit_meta")}
        | {"entry": {ek: entry.get(ek) for ek in sorted(entry)}},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _order_key(order: Order) -> str:
    return f"{order.setup_id or ''}:{order.signal_index}:{order.limit}:{order.direction}"


def berg_forward_step(
    runtime: BergForwardRuntime,
    spec: dict,
    bars_5m: list[Bar],
    bars_4h: list[Bar],
    tick: Decimal,
) -> tuple[BergForwardRuntime, list[Order], list[OrderAmendment], dict[int, dict]]:
    bar_index = len(bars_5m) - 1
    if bar_index < 0:
        return runtime, [], [], {}
    if bar_index <= runtime.last_bar_index:
        return runtime, [], [], {}

    if len(bars_4h) < 3:
        return runtime, [], [], {}

    c_hash = _config_hash(spec)
    if runtime.config_hash and runtime.config_hash != c_hash:
        raise ValueError("Berg strategy configuration changed — reset forward runtime")
    runtime.config_hash = c_hash

    if bars_4h:
        runtime.bars_4h_last_ts = bars_4h[-1].ts.isoformat()

    spec_fwd = {**spec, "forward_test": True, "_fsm_state": runtime.fsm_state or None}
    engine = BergTnbEngine(spec_fwd, bars_5m, tick)
    _setups, orders, _events, _rej = engine.run(through_bar=bar_index)
    snapshots = getattr(engine, "_forward_snapshots", {})

    if getattr(engine, "_fsm_export", None):
        runtime.fsm_state = engine._fsm_export.to_dict()

    new_orders: list[Order] = []
    amendments: list[OrderAmendment] = []
    for order in orders:
        if order.signal_index != bar_index:
            continue
        key = _order_key(order)
        if key in runtime.placed_order_keys:
            continue
        runtime.placed_order_keys.append(key)
        new_orders.append(order)

    for order in orders:
        if order.signal_index > bar_index:
            continue
        for amd in order.amendments:
            if amd.bar_index == bar_index:
                amendments.append(amd)

    runtime.last_bar_index = bar_index
    runtime.last_snapshot = snapshots.get(bar_index) or runtime.last_snapshot
    return runtime, new_orders, amendments, snapshots