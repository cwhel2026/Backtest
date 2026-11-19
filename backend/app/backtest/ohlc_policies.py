"""Conservative OHLC execution policies and explicit ambiguity labels.

Bar-level data cannot prove intrabar event order. Policies here pick conservative,
labelled outcomes and record uncertainty — not fabricated precision.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.backtest.bars import Bar
from app.backtest.exits import check_intrabar_exit


class EntryBarExitPolicy(str, Enum):
    """Exit handling on the bar where a limit fill is recognised."""

    SKIP_EXITS = "skip_exits"
    CONSERVATIVE_OHLC = "conservative_ohlc"


class PendingFillPolicy(str, Enum):
    """When limit and protective stop are both within the same bar's range (pending order)."""

    ALLOW_FILL_THEN_EXIT = "allow_fill_then_exit"
    NO_FILL_IF_STOP_TOUCHED = "no_fill_if_stop_touched"


@dataclass(frozen=True)
class ExitEvaluation:
    price: Decimal | None
    reason: str | None
    uncertainties: tuple[str, ...] = ()


def _map_reason(raw: str | None) -> str | None:
    if raw is None:
        return None
    if "take_profit" in raw:
        return "target"
    if "gap" in raw:
        return "stop_gap"
    if "stop" in raw:
        return "stop"
    return raw


def evaluate_fill_bar_exit(
    direction: str,
    stop: Decimal,
    target: Decimal,
    bar: Bar,
    policy: EntryBarExitPolicy,
) -> ExitEvaluation:
    if policy == EntryBarExitPolicy.SKIP_EXITS:
        return ExitEvaluation(None, None, ())
    px, raw = check_intrabar_exit(direction, stop, target, bar)
    if px is None:
        return ExitEvaluation(None, None, ())
    uncertainties: list[str] = []
    if direction == "long":
        stop_hit = bar.low <= stop
        target_hit = bar.high >= target
    else:
        stop_hit = bar.high >= stop
        target_hit = bar.low <= target
    if stop_hit and target_hit:
        uncertainties.append("fill_bar_stop_and_target_same_bar_stop_first")
    return ExitEvaluation(px, _map_reason(raw), tuple(uncertainties))


def pending_limit_fill_eligible(
    direction: str,
    limit: Decimal,
    stop: Decimal,
    bar: Bar,
    policy: PendingFillPolicy,
) -> tuple[bool, tuple[str, ...]]:
    """Return whether OHLC allows a limit fill on this bar and any uncertainty tags."""
    from app.backtest.execution import limit_touched

    if not limit_touched(direction, limit, bar):
        return False, ()
    if policy == PendingFillPolicy.ALLOW_FILL_THEN_EXIT:
        return True, ("limit_touch_eligibility_not_live_fill",)
    if direction == "long":
        if bar.low <= stop and stop < limit:
            return False, ("pending_stop_touched_same_bar_no_fill_conservative",)
    else:
        if bar.high >= stop and stop > limit:
            return False, ("pending_stop_touched_same_bar_no_fill_conservative",)
    return True, ("limit_touch_eligibility_not_live_fill",)