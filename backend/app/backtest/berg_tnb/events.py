"""Emit Berg TNB decision events from pipeline transitions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from app.backtest.decision_events import DecisionEvent, DecisionEventType, SourceClass

if TYPE_CHECKING:
    from app.backtest.berg_tnb.types import BergTnbState


def emit(
    out: list[DecisionEvent],
    *,
    ts: datetime,
    bar_index: int,
    event_type: DecisionEventType,
    setup_id: str,
    direction: str | None,
    explanation: str,
    rule_id: str,
    source: SourceClass,
    levels: dict | None = None,
    instrument: str | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> None:
    out.append(
        DecisionEvent(
            ts=ts,
            bar_index=bar_index,
            event_type=event_type,
            strategy="berg_tnb_model_v1",
            strategy_version="v1",
            setup_id=setup_id,
            direction=direction,
            explanation=explanation,
            rule_id=rule_id,
            source=source,
            levels=levels or {},
            instrument=instrument,
            data_available_ts=ts,
            before_state=before_state,
            after_state=after_state,
        )
    )


def state_to_event(frm: str, to: str) -> DecisionEventType | None:
    mapping = {
        "WAITING_FOR_SESSION_LEVEL->WAITING_FOR_SWEEP": DecisionEventType.SESSION_LEVEL_FINALIZED,
        "WAITING_FOR_SWEEP->WAITING_FOR_REVERSAL_CANDLE": DecisionEventType.LIQUIDITY_SWEEP_DETECTED,
        "WAITING_FOR_REVERSAL_CANDLE->WAITING_FOR_FAKEOUT_0079": DecisionEventType.REVERSAL_CONFIRMED,
        "WAITING_FOR_FAKEOUT_0079->WAITING_FOR_5M_BOS": DecisionEventType.FAKEOUT_CONFIRMED,
        "WAITING_FOR_5M_BOS->TRACKING_ENTRY_FIB": DecisionEventType.BOS_CONFIRMED,
    }
    return mapping.get(f"{frm}->{to}")