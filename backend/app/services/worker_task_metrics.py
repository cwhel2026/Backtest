"""Normalize Celery tick outcomes for WorkerHealthBeat.detail."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.util.log_events import log_event

_tick_logger = logging.getLogger("app.worker.tick")


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
        "setups_detected",
        "setups_written",
        "runs_touched",
        "allow_trading",
        "connection_status",
        "error",
        "skipped",
        "summary",
        "idle_reason",
        "disabled",
        "reason",
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
    if res.get("idle_reason") and "idle_reason" not in out:
        out["idle_reason"] = res["idle_reason"]
    return out


def emit_tick_log(detail: dict) -> None:
    """One Railway-visible line per Celery tick (metrics also live in worker_health_beats)."""
    task = detail.get("task", "worker_tick")
    compact = {k: detail[k] for k in (
        "work_done",
        "idle_reason",
        "events",
        "candles",
        "candles_closed",
        "setups_detected",
        "provider",
        "runs_touched",
        "error",
        "disabled",
        "reason",
    ) if k in detail}
    level = logging.WARNING if detail.get("ok") is False or detail.get("error") else logging.INFO
    if compact.get("work_done") is False and not compact.get("error"):
        level = logging.INFO
    log_event(_tick_logger, level, task, **compact)


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