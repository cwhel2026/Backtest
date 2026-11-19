"""No-lookahead guards for forward testing."""

from __future__ import annotations

from datetime import datetime


def assert_decision_not_before_bar_close(bar_close_exchange_ts: datetime, decision_ts: datetime) -> None:
    if decision_ts < bar_close_exchange_ts:
        raise AssertionError(
            f"Decision at {decision_ts.isoformat()} precedes bar close {bar_close_exchange_ts.isoformat()}"
        )