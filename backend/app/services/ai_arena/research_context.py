"""Derived market statistics for AI — no raw licensed OHLCV export."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai_arena import AiExperiment
from app.services.market_data.ohlcv_cache import latest_dataset


def market_stats_for_symbol(session: Session, symbol: str, timeframe: str = "5m") -> dict:
    picked = latest_dataset(session, symbol, timeframe)
    if not picked:
        return {"symbol": symbol, "available": False, "note": "No validated dataset in catalogue for summary stats."}
    lineage = (picked.meta or {}).get("data_lineage") or {}
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "available": True,
        "row_count": picked.row_count,
        "validation_status": picked.validation_status.value,
        "coverage_start": picked.coverage_start.isoformat() if picked.coverage_start else None,
        "coverage_end": picked.coverage_end.isoformat() if picked.coverage_end else None,
        "lineage_tier": lineage.get("tier"),
        "aggregates_only": True,
        "note": "Bar-level OHLCV is not sent to third-party LLMs — only dataset metadata and prior experiment summaries.",
    }


def researcher_memory_summary(session: Session, researcher_id, *, limit: int = 12) -> dict:
    exps = session.execute(
        select(AiExperiment)
        .where(AiExperiment.researcher_id == researcher_id)
        .order_by(AiExperiment.created_at.desc())
        .limit(limit)
    ).scalars().all()
    successes = [e for e in exps if e.status == "validated"]
    failures = [e for e in exps if e.status in ("rejected", "duplicate", "failed_validation")]
    return {
        "recent_experiments": len(exps),
        "validated_count": len(successes),
        "rejected_count": len(failures),
        "last_families": list({e.strategy_family for e in exps if e.strategy_family})[:8],
        "failures_sample": [
            {"family": e.strategy_family, "reason": (e.rejection_reason or "")[:120]} for e in failures[:5]
        ],
        "success_metrics_sample": [
            {"family": e.strategy_family, "metrics": e.validation_metrics} for e in successes[:3]
        ],
    }