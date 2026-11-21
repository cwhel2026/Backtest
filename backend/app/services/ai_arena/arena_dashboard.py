"""AI Research Arena dashboard aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.ai_arena import AiApiUsage, AiExperiment, AiResearcher
from app.services.ai_arena.bootstrap import ensure_ai_researchers
from app.services.ai_arena.budget import spend_usd
from app.services.ai_arena.llm_providers import list_provider_catalog


def build_arena_dashboard(session: Session) -> dict:
    researchers = ensure_ai_researchers(session)
    session.flush()
    cards = []
    for r in researchers:
        daily = spend_usd(session, r.id, day=True)
        monthly = spend_usd(session, r.id, day=False)
        exp_counts = session.execute(
            select(AiExperiment.status, func.count())
            .where(AiExperiment.researcher_id == r.id)
            .group_by(AiExperiment.status)
        ).all()
        by_status = {status: int(n) for status, n in exp_counts}
        cards.append(
            {
                "id": str(r.id),
                "provider_slug": r.provider_slug,
                "display_name": r.display_name,
                "enabled": r.enabled,
                "activated_by_user": r.activated_by_user,
                "connection_status": r.connection_status,
                "model_id": r.model_id,
                "current_activity": r.current_activity,
                "last_cycle_at": r.last_cycle_at.isoformat() if r.last_cycle_at else None,
                "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None,
                "stats": r.stats,
                "daily_spend_usd": float(daily),
                "monthly_spend_usd": float(monthly),
                "daily_budget_usd": float(r.daily_budget_usd),
                "monthly_budget_usd": float(r.monthly_budget_usd),
                "experiments_by_status": by_status,
                "research_frequency_minutes": r.research_frequency_minutes,
            }
        )

    leaderboard = _leaderboard(session)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "researchers": cards,
        "provider_catalog": list_provider_catalog(),
        "leaderboard": leaderboard,
        "note": "Performance ranks use validated backtest metrics only — not LLM self-assessment.",
    }


def _leaderboard(session: Session) -> list[dict]:
    rows = session.execute(
        select(AiExperiment)
        .where(AiExperiment.status == "validated")
        .order_by(desc(AiExperiment.completed_at))
        .limit(50)
    ).scalars().all()
    ranked = []
    for e in rows:
        m = e.validation_metrics or {}
        ranked.append(
            {
                "experiment_id": str(e.id),
                "provider_slug": e.author_provider_slug,
                "family": e.strategy_family,
                "symbol": e.symbol,
                "net_pnl": m.get("net_pnl"),
                "trade_count": m.get("trade_count"),
                "max_drawdown": m.get("max_drawdown"),
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
            }
        )
    ranked.sort(key=lambda x: (x.get("net_pnl") or 0), reverse=True)
    return ranked[:20]


def researcher_detail(session: Session, slug: str) -> dict:
    r = session.execute(select(AiResearcher).where(AiResearcher.provider_slug == slug)).scalar_one_or_none()
    if not r:
        raise ValueError("Unknown researcher")
    exps = session.execute(
        select(AiExperiment).where(AiExperiment.researcher_id == r.id).order_by(desc(AiExperiment.created_at)).limit(40)
    ).scalars().all()
    return {
        "researcher": {
            "id": str(r.id),
            "provider_slug": r.provider_slug,
            "display_name": r.display_name,
            "enabled": r.enabled,
            "model_id": r.model_id,
            "memory": r.memory,
            "objectives": r.objectives,
            "stats": r.stats,
            "current_activity": r.current_activity,
        },
        "experiments": [
            {
                "id": str(e.id),
                "status": e.status,
                "family": e.strategy_family,
                "symbol": e.symbol,
                "hypothesis": e.hypothesis,
                "rejection_reason": e.rejection_reason,
                "metrics": e.validation_metrics,
                "backtest_run_id": str(e.backtest_run_id) if e.backtest_run_id else None,
                "created_at": e.created_at.isoformat(),
            }
            for e in exps
        ],
    }