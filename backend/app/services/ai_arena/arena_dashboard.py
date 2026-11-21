"""AI Research Arena dashboard aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.ai_arena import AiApiUsage, AiArenaSettings, AiExperiment, AiResearcher
from app.services.ai_arena.bootstrap import ensure_ai_researchers
from app.services.ai_arena.budget import spend_usd
from app.services.ai_arena.guardrails import get_or_create_settings, global_spend_usd
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
    settings = get_or_create_settings(session)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "researchers": cards,
        "provider_catalog": list_provider_catalog(),
        "leaderboard": leaderboard,
        "global": {
            "emergency_stop": settings.emergency_stop,
            "global_daily_budget_usd": float(settings.global_daily_budget_usd),
            "global_monthly_budget_usd": float(settings.global_monthly_budget_usd),
            "global_daily_spend_usd": float(global_spend_usd(session, day=True)),
            "global_monthly_spend_usd": float(global_spend_usd(session, day=False)),
            "auto_paper_promotion": settings.auto_paper_promotion,
        },
        "note": "Leaderboard ranks researchers on composite score — not top historical P&L alone.",
    }


def _leaderboard(session: Session) -> list[dict]:
    researchers = session.execute(select(AiResearcher)).scalars().all()
    rows: list[dict] = []
    for r in researchers:
        exps = session.execute(select(AiExperiment).where(AiExperiment.researcher_id == r.id)).scalars().all()
        validated = [e for e in exps if e.validation_tier == "validated" or e.status == "validated"]
        failed = [e for e in exps if e.status in ("rejected", "duplicate", "failed_validation")]
        tested_fps = {e.spec_fingerprint for e in exps if e.spec_fingerprint}
        total_cost = spend_usd(session, r.id, day=False)
        best_oos_pf = 0.0
        worst_dd = 0.0
        for e in validated:
            m = e.validation_metrics or {}
            best_oos_pf = max(best_oos_pf, float(m.get("profit_factor") or 0))
            worst_dd = max(worst_dd, float(m.get("max_drawdown") or 0))
        cost_per_valid = float(total_cost / len(validated)) if validated else None
        composite = (
            len(validated) * 100
            + len(tested_fps) * 5
            + best_oos_pf * 20
            - len(failed) * 2
            - worst_dd / 500
            - float(total_cost) * 10
        )
        rows.append(
            {
                "provider_slug": r.provider_slug,
                "display_name": r.display_name,
                "strategies_generated": int((r.stats or {}).get("generated") or len(exps)),
                "unique_tested": len(tested_fps),
                "failed": len(failed),
                "validated": len(validated),
                "experimental": len([e for e in exps if e.status == "experimental"]),
                "best_profit_factor": best_oos_pf,
                "max_drawdown_worst": worst_dd,
                "monthly_research_cost_usd": float(total_cost),
                "cost_per_validated_strategy_usd": cost_per_valid,
                "composite_score": round(composite, 2),
            }
        )
    rows.sort(key=lambda x: x["composite_score"], reverse=True)
    return rows


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
                "validation_tier": e.validation_tier,
                "lifecycle_phase": e.lifecycle_phase,
                "family": e.strategy_family,
                "symbol": e.symbol,
                "hypothesis": e.hypothesis,
                "reasoning_summary": e.reasoning_summary,
                "rejection_reason": e.rejection_reason,
                "metrics": e.validation_metrics,
                "lineage": e.lineage,
                "backtest_run_id": str(e.backtest_run_id) if e.backtest_run_id else None,
                "created_at": e.created_at.isoformat(),
            }
            for e in exps
        ],
    }