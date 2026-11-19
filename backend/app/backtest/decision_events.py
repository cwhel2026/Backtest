"""Structured decision events for strategy fidelity / debugger replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

SourceClass = Literal["pdf_confirmed", "interpretation", "experimental"]


class DecisionEventType(str, Enum):
    BIAS_CONFIRMED = "BIAS_CONFIRMED"
    SESSION_LEVEL_FINALIZED = "SESSION_LEVEL_FINALIZED"
    LIQUIDITY_SWEEP_DETECTED = "LIQUIDITY_SWEEP_DETECTED"
    REVERSAL_CONFIRMED = "REVERSAL_CONFIRMED"
    FAKEOUT_CONFIRMED = "FAKEOUT_CONFIRMED"
    BOS_CONFIRMED = "BOS_CONFIRMED"
    FIB_ANCHOR_CREATED = "FIB_ANCHOR_CREATED"
    FIB_ANCHOR_UPDATED = "FIB_ANCHOR_UPDATED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_AMENDED = "ORDER_AMENDED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    STOP_TRIGGERED = "STOP_TRIGGERED"
    TARGET_TRIGGERED = "TARGET_TRIGGERED"
    SETUP_INVALIDATED = "SETUP_INVALIDATED"
    SETUP_REJECTED = "SETUP_REJECTED"


@dataclass
class DecisionEvent:
    ts: datetime
    bar_index: int
    event_type: DecisionEventType
    strategy: str
    strategy_version: str
    setup_id: str
    direction: str | None
    explanation: str
    rule_id: str
    source: SourceClass
    timeframe: str = "5m"
    instrument: str | None = None
    levels: dict[str, Any] = field(default_factory=dict)
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    data_available_ts: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["ts"] = self.ts.isoformat()
        if self.data_available_ts:
            d["data_available_ts"] = self.data_available_ts.isoformat()
        return _decimal_safe(d)


@dataclass
class RejectedSetup:
    ts: datetime
    bar_index: int
    strategy: str
    setup_id: str
    reason_code: str
    explanation: str
    rule_id: str
    source: SourceClass
    candidate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "bar_index": self.bar_index,
            "strategy": self.strategy,
            "setup_id": self.setup_id,
            "reason_code": self.reason_code,
            "explanation": self.explanation,
            "rule_id": self.rule_id,
            "source": self.source,
            "candidate": self.candidate,
        }


def merge_execution_events(
    base: list[DecisionEvent],
    order_events: list[dict],
    *,
    strategy: str,
    setup_id: str,
    bar_index_lookup: dict[str, int] | None = None,
    include_placed: bool = True,
) -> list[DecisionEvent]:
    """Map video_execution order_events into decision events."""
    out = list(base)
    lookup = bar_index_lookup or {}
    for oe in order_events:
        ts_s = oe.get("ts")
        if not ts_s:
            continue
        ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
        ev = (oe.get("event") or "").lower()
        et = {
            "placed": DecisionEventType.ORDER_SUBMITTED,
            "filled": DecisionEventType.ORDER_FILLED,
            "expired": DecisionEventType.ORDER_EXPIRED,
            "cancelled": DecisionEventType.ORDER_CANCELLED,
            "amended": DecisionEventType.ORDER_AMENDED,
        }.get(ev)
        if not et or (ev == "placed" and not include_placed):
            continue
        out.append(
            DecisionEvent(
                ts=ts,
                bar_index=lookup.get(ts_s, -1),
                event_type=et,
                strategy=strategy,
                strategy_version="v1",
                setup_id=setup_id,
                direction=None,
                explanation=oe.get("detail") or ev,
                rule_id="execution.ohlc",
                source="interpretation",
                levels={"price": oe.get("price")},
                data_available_ts=ts,
            )
        )
    return out


def _decimal_safe(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _decimal_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_safe(x) for x in obj]
    return obj