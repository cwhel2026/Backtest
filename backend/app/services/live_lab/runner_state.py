"""Versioned forward-test runner_state (executor + strategy FSM)."""

from __future__ import annotations

from typing import Any

from app.services.live_lab.incremental_executor import ForwardExecutorState, IncrementalVideoForwardEngine


RUNNER_STATE_VERSION = 3


def load_runner_state(raw: dict | None) -> tuple[ForwardExecutorState, dict[str, Any]]:
    raw = dict(raw or {})
    if raw.get("version") == 3:
        ex_raw = raw.get("executor") or {}
        strat = dict(raw.get("strategy_fsm") or {})
        return ForwardExecutorState(
            version=int(ex_raw.get("version", 2)),
            last_bar_ts=ex_raw.get("last_bar_ts"),
            bars_count=int(ex_raw.get("bars_count", 0)),
            busy_until=int(ex_raw.get("busy_until", -1)),
            pending=list(ex_raw.get("pending") or []),
            open_position=ex_raw.get("open_position"),
            placed_setup_keys=list(ex_raw.get("placed_setup_keys") or []),
            stats=dict(ex_raw.get("stats") or {}),
        ), strat
    if raw.get("version") == 2:
        return ForwardExecutorState(
            version=2,
            last_bar_ts=raw.get("last_bar_ts"),
            bars_count=int(raw.get("bars_count", 0)),
            busy_until=int(raw.get("busy_until", -1)),
            pending=list(raw.get("pending") or []),
            open_position=raw.get("open_position"),
            placed_setup_keys=list(raw.get("placed_setup_keys") or []),
            stats=dict(raw.get("stats") or {}),
        ), {"berg_runtime": raw.get("berg_runtime"), "video_runtime": raw.get("video_runtime")}
    return ForwardExecutorState(), {}


def save_runner_state(
    eng: IncrementalVideoForwardEngine,
    strategy_fsm: dict[str, Any],
) -> dict[str, Any]:
    st = eng.state
    return {
        "version": RUNNER_STATE_VERSION,
        "executor": {
            "version": 2,
            "last_bar_ts": st.last_bar_ts,
            "bars_count": st.bars_count,
            "busy_until": st.busy_until,
            "pending": st.pending,
            "open_position": st.open_position,
            "placed_setup_keys": st.placed_setup_keys,
            "stats": {
                "orders_placed": eng.stats.orders_placed,
                "orders_filled": eng.stats.orders_filled,
                "orders_expired": eng.stats.orders_expired,
            },
        },
        "strategy_fsm": strategy_fsm,
    }