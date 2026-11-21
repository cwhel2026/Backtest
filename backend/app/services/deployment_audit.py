"""Read-only production verification bundle — no paid downloads, no data mutation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.market_data import HistoricalDataset
from app.models.research import ResearchJob
from app.models.scanner import WorkerHealthBeat
from app.models.strategy import StrategyDefinition
from app.services.cme_market_clock import cme_futures_market_status
from app.services.market_data.dataset_research import research_eligibility
from app.services.market_data.storage_backend import ensure_ohlcv_storage, resolved_store_path
from app.services.market_data.databento_client import check_dataset_range, quote_download_cost
from app.worker.celery_app import celery_app


def _alembic_revision(session: Session) -> dict:
    try:
        row = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        return {"revision": row, "expected_head": "012"}
    except Exception as exc:
        return {"revision": None, "error": str(exc)[:200]}


def _dataset_storage_audit(session: Session) -> dict:
    root = resolved_store_path()
    rows = session.execute(select(HistoricalDataset).order_by(HistoricalDataset.downloaded_at.desc())).scalars().all()
    items: list[dict] = []
    on_volume = 0
    missing_parquet = 0
    for ds in rows:
        folder = root / str(ds.id)
        parquet_files = list(folder.glob("*.parquet")) if folder.is_dir() else []
        elig = research_eligibility(ds)
        lineage = (ds.meta or {}).get("data_lineage")
        item = {
            "id": str(ds.id),
            "timeframe": ds.timeframe,
            "row_count": ds.row_count,
            "validation_status": ds.validation_status.value,
            "storage_uri": ds.storage_uri,
            "store_path": str(folder),
            "parquet_files": len(parquet_files),
            "on_disk": bool(parquet_files),
            "lineage_present": bool(lineage),
            "research_eligible": elig.ok,
            "research_reason": None if elig.ok else elig.reason,
        }
        if parquet_files:
            on_volume += 1
        else:
            missing_parquet += 1
        items.append(item)
    return {
        "ohlcv_root": str(root.resolve()),
        "volume_mount_seen": Path("/data").is_dir(),
        "dataset_count": len(items),
        "datasets_with_parquet": on_volume,
        "datasets_missing_parquet": missing_parquet,
        "datasets": items[:50],
    }


def _worker_activity_audit(session: Session) -> dict:
    beats = session.execute(select(WorkerHealthBeat)).scalars().all()
    out = []
    for b in beats:
        detail = dict(b.detail or {})
        out.append(
            {
                "worker_name": b.worker_name,
                "last_success_at": b.last_success_at.isoformat() if b.last_success_at else None,
                "detail": detail,
                "work_done": detail.get("work_done"),
                "idle_reason": detail.get("idle_reason"),
                "events": detail.get("events"),
                "candles": detail.get("candles") or detail.get("candles_closed"),
                "setups_detected": detail.get("setups_detected") or (detail.get("scanner") or {}).get("setups_written"),
                "opened": detail.get("opened"),
                "closed": detail.get("closed"),
            }
        )
    return {"beats": out}


def _celery_queue_audit() -> dict:
    routes = dict(celery_app.conf.task_routes or {})
    return {
        "task_routes": routes,
        "realtime_tasks": [k for k, v in routes.items() if v.get("queue") == "realtime"],
        "research_tasks": [k for k, v in routes.items() if v.get("queue") == "research"],
        "note": "Realtime and research workers must consume separate queues (see railway-start-simple.sh).",
    }


def databento_probe(*, cost_window_hours: int = 24) -> dict:
    """API connectivity: get_cost + get_dataset_range only — does not download bars."""
    settings = get_settings()
    if not settings.databento_configured:
        return {"configured": False, "reason": "DATABENTO_API_KEY not set on server"}
    end = datetime.now(UTC)
    start = end - __import__("datetime").timedelta(hours=max(1, cost_window_hours))
    cost = quote_download_cost("MES", start, end)
    entitlement = check_dataset_range(start, end)
    return {
        "configured": True,
        "cost_probe": cost.to_dict() if hasattr(cost, "to_dict") else {"usd": cost.usd, "source": cost.source, "note": cost.note},
        "entitlement": entitlement,
        "download_performed": False,
    }


def build_deployment_audit(session: Session) -> dict[str, Any]:
    settings = get_settings()
    storage_boot = ensure_ohlcv_storage()
    strategies = session.execute(select(StrategyDefinition).order_by(StrategyDefinition.created_at)).scalars().all()
    last_jobs = session.execute(select(ResearchJob).order_by(ResearchJob.created_at.desc()).limit(5)).scalars().all()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "on_railway": settings.on_railway,
            "ohlcv_store_dir": settings.ohlcv_store_dir,
            "live_lab_provider": settings.live_lab_provider,
            "live_lab_tick_enabled": settings.live_lab_tick_enabled,
            "autonomous_hourly_enabled": settings.autonomous_hourly_enabled,
        },
        "storage_bootstrap": storage_boot,
        "database_migration": _alembic_revision(session),
        "datasets": _dataset_storage_audit(session),
        "strategies_registered": [{"id": str(s.id), "name": s.name, "timeframe": s.timeframe} for s in strategies],
        "recent_research_jobs": [
            {
                "id": str(j.id),
                "title": j.title,
                "status": j.status.value,
                "message": j.message,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in last_jobs
        ],
        "worker_ticks": _worker_activity_audit(session),
        "celery": _celery_queue_audit(),
        "cme_market": cme_futures_market_status(),
        "databento": databento_probe(cost_window_hours=24),
        "live_lab_idle_hint": (
            "Default LIVE_LAB_PROVIDER=replay needs LIVE_LAB_REPLAY_PATH or delayed_bars/event_store for non-zero events."
            if (settings.live_lab_provider or "replay") == "replay"
            else None
        ),
    }