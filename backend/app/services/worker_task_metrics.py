"""Normalize Celery tick outcomes for WorkerHealthBeat.detail."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def merge_tick_detail(base: dict | None, result: dict | None, *, task: str) -> dict:
    out = dict(base or {})
    out["task"] = task
    out["last_tick_at"] = datetime.now(UTC).isoformat()
    res = result or {}
    if res.get("disabled"):
        out["idle_reason"] = res.get("reason", "disabled_in_settings")
        return out
    if not res:
        out["idle_reason"] = "no_result_payload"
        return out
    for key in (
        "ok",
        "events",
        "candles",
        "candles_closed",
        "provider",
        "latency_mode",
        "setups_written",
        "runs_touched",
        "allow_trading",
        "error",
        "skipped",
        "summary",
    ):
        if key in res:
            out[key] = res[key]
    if res.get("ok") is False and res.get("error"):
        out["work_done"] = False
        out["failure_reason"] = res.get("error")
    elif res.get("events") == 0 and res.get("candles") == 0:
        out["work_done"] = False
        out["idle_reason"] = res.get("idle_reason", "no_market_events_this_tick")
    else:
        out["work_done"] = True
    return out


def paper_tick_detail(result: dict[str, Any]) -> dict:
    return {
        "task": "paper_forward_tick",
        "last_tick_at": datetime.now(UTC).isoformat(),
        "opened": result.get("opened", 0),
        "closed": result.get("closed", 0),
        "refreshed": result.get("refreshed", 0),
        "enrolled_new": result.get("enrolled_new", 0),
        "work_done": bool(result.get("opened") or result.get("closed") or result.get("refreshed")),
        "errors": result.get("refresh_errors"),
    }