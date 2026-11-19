"""Types and state machine labels for Berg TNB v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal


class BergTnbState(str, Enum):
    WAITING_FOR_4H_BIAS = "WAITING_FOR_4H_BIAS"
    WAITING_FOR_SESSION_LEVEL = "WAITING_FOR_SESSION_LEVEL"
    WAITING_FOR_SWEEP = "WAITING_FOR_SWEEP"
    WAITING_FOR_REVERSAL_CANDLE = "WAITING_FOR_REVERSAL_CANDLE"
    WAITING_FOR_FAKEOUT_0079 = "WAITING_FOR_FAKEOUT_0079"
    WAITING_FOR_5M_BOS = "WAITING_FOR_5M_BOS"
    TRACKING_ENTRY_FIB = "TRACKING_ENTRY_FIB"
    LIMIT_ORDER_PENDING = "LIMIT_ORDER_PENDING"
    POSITION_OPEN = "POSITION_OPEN"
    COMPLETED = "COMPLETED"
    INVALIDATED_OR_EXPIRED = "INVALIDATED_OR_EXPIRED"


BiasDir = Literal["bullish", "bearish"]


@dataclass
class StateTransition:
    ts: datetime
    from_state: BergTnbState
    to_state: BergTnbState
    bar_index: int
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    config_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass
class Bias4hRecord:
    direction: BiasDir | None
    fractal_level: Decimal | None
    bos_ts: datetime | None
    fractal_confirm_index: int | None
    bos_bar_index: int | None
    fractal_definition: str


@dataclass
class SessionLevelRecord:
    session_id: str
    measurement_start: datetime
    measurement_end: datetime
    session_high: Decimal
    session_low: Decimal
    liquidity_level: Decimal
    bias: BiasDir
    profile: str
    setup_preset: str


@dataclass
class SweepRecord:
    touch_ts: datetime
    bar_index: int
    max_penetration: Decimal
    touch_kind: str
    ohlc: dict[str, str]


@dataclass
class FakeoutFibRecord:
    anchor_high: Decimal
    anchor_low: Decimal
    anchor_high_ts: datetime
    anchor_low_ts: datetime
    level_0079: Decimal
    confirmed_ts: datetime | None
    bar_index: int | None


@dataclass
class Bos5mRecord:
    structure_level: Decimal
    fractal_confirm_index: int
    bos_ts: datetime
    bos_bar_index: int
    direction: BiasDir
    ticks_beyond: int


@dataclass
class EntryFibRecord:
    anchor_low: Decimal
    anchor_high: Decimal
    anchor_low_ts: datetime
    anchor_high_ts: datetime
    entry_ratio: Decimal
    limit_price: Decimal
    updates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BergTnbSetup:
    setup_id: str
    transitions: list[StateTransition]
    bias: Bias4hRecord | None = None
    session_level: SessionLevelRecord | None = None
    sweep: SweepRecord | None = None
    reversal_bar_index: int | None = None
    fakeout: FakeoutFibRecord | None = None
    bos: Bos5mRecord | None = None
    entry_fib: EntryFibRecord | None = None
    order_index: int | None = None
    final_state: BergTnbState = BergTnbState.WAITING_FOR_4H_BIAS