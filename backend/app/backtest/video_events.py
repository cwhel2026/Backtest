"""Emit decision events during video strategy order discovery (bar-known only)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.backtest.decision_events import DecisionEvent, DecisionEventType, RejectedSetup, SourceClass


def _emit(
    out: list[DecisionEvent],
    *,
    ts: datetime,
    bar_index: int,
    strategy: str,
    event_type: DecisionEventType,
    explanation: str,
    rule_id: str,
    source: SourceClass = "pdf_confirmed",
    setup_id: str | None = None,
    direction: str | None = None,
    levels: dict | None = None,
) -> None:
    out.append(
        DecisionEvent(
            ts=ts,
            bar_index=bar_index,
            event_type=event_type,
            strategy=strategy,
            strategy_version="v1",
            setup_id=setup_id or f"{strategy}-{bar_index}",
            direction=direction,
            explanation=explanation,
            rule_id=rule_id,
            source=source,
            levels=levels or {},
            data_available_ts=ts,
        )
    )


def reject(
    out: list[RejectedSetup],
    *,
    ts: datetime,
    bar_index: int,
    strategy: str,
    setup_id: str,
    reason_code: str,
    explanation: str,
    rule_id: str,
) -> None:
    out.append(
        RejectedSetup(
            ts=ts,
            bar_index=bar_index,
            strategy=strategy,
            setup_id=setup_id,
            reason_code=reason_code,
            explanation=explanation,
            rule_id=rule_id,
            source="interpretation",
        )
    )


def sweep_detected(
    events: list[DecisionEvent],
    *,
    strategy: str,
    ts: datetime,
    bar_index: int,
    direction: str,
    level: Decimal,
    setup_id: str,
) -> None:
    _emit(
        events,
        ts=ts,
        bar_index=bar_index,
        strategy=strategy,
        event_type=DecisionEventType.LIQUIDITY_SWEEP_DETECTED,
        explanation=f"Session liquidity sweep ({direction})",
        rule_id="video.session_sweep",
        setup_id=setup_id,
        direction=direction,
        levels={"liquidity_level": str(level)},
    )


def bos_confirmed(
    events: list[DecisionEvent],
    *,
    strategy: str,
    ts: datetime,
    bar_index: int,
    direction: str,
    level: Decimal,
    setup_id: str,
) -> None:
    _emit(
        events,
        ts=ts,
        bar_index=bar_index,
        strategy=strategy,
        event_type=DecisionEventType.BOS_CONFIRMED,
        explanation="Close break of structure vs prior pivot",
        rule_id="video.bos_close",
        setup_id=setup_id,
        direction=direction,
        levels={"structure_level": str(level)},
    )


def order_submitted(
    events: list[DecisionEvent],
    *,
    strategy: str,
    ts: datetime,
    bar_index: int,
    direction: Literal["long", "short"],
    limit: Decimal,
    stop: Decimal,
    target: Decimal,
    setup_id: str,
    reason: str,
) -> None:
    _emit(
        events,
        ts=ts,
        bar_index=bar_index,
        strategy=strategy,
        event_type=DecisionEventType.ORDER_SUBMITTED,
        explanation=reason,
        rule_id="video.order_submit",
        setup_id=setup_id,
        direction=direction,
        levels={"limit": str(limit), "stop": str(stop), "target": str(target)},
    )