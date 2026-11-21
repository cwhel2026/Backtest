"""AI Research Arena dashboard aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.ai_arena import AiApiUsage, AiArenaSettings, AiExperiment, AiResearchCycle, AiResearcher
from app.services.ai_arena.bootstrap import ensure_ai_researchers
from app.services.ai_arena.budget import spend_usd
from app.services.ai_arena.guardrails import get_or_create_settings, global_spend_usd
from app.services.ai_arena.llm_providers import list_provider_catalog
from app.services.ai_arena.research_memory import memory_context_for_llm
from app.services.ai_arena.paper_stats import paper_stats_for_researcher


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
        paper = paper_stats_for_researcher(session, r)
        refinements = int((r.stats or {}).get("refinements") or sum(1 for e in exps if e.parent_experiment_id))
        families = len({e.strategy_family for e in exps if e.strategy_family})
        composite = (
            len(validated) * 100
            + len(tested_fps) * 5
            + best_oos_pf * 20
            - len(failed) * 2
            - worst_dd / 500
            - float(total_cost) * 10
        )
        if not paper.get("insufficient_sample"):
            composite += float(paper.get("paper_net_pnl") or 0) / 50
            composite += float(paper.get("paper_profit_factor") or 0) * 5
        rows.append(
            {
                "provider_slug": r.provider_slug,
                "display_name": r.display_name,
                "strategies_generated": int((r.stats or {}).get("generated") or len(exps)),
                "unique_experiments": len(tested_fps),
                "families_explored": families,
                "refinements_completed": refinements,
                "failed": len(failed),
                "validated": len(validated),
                "experimental": len([e for e in exps if e.status == "experimental"]),
                "historical_best_profit_factor": best_oos_pf,
                "historical_max_drawdown": worst_dd,
                "active_forward_strategies": paper.get("active_forward_strategies", 0),
                "closed_paper_trades": paper.get("closed_paper_trades", 0),
                "paper_net_pnl": paper.get("paper_net_pnl"),
                "paper_win_rate": paper.get("paper_win_rate"),
                "paper_profit_factor": paper.get("paper_profit_factor"),
                "paper_max_drawdown": paper.get("paper_max_drawdown"),
                "paper_insufficient_sample": paper.get("insufficient_sample", True),
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
        select(AiExperiment).where(AiExperiment.researcher_id == r.id).order_by(desc(AiExperiment.created_at)).limit(80)
    ).scalars().all()
    cycles = session.execute(
        select(AiResearchCycle).where(AiResearchCycle.researcher_id == r.id).order_by(desc(AiResearchCycle.started_at)).limit(20)
    ).scalars().all()
    monthly = spend_usd(session, r.id, day=False)
    daily = spend_usd(session, r.id, day=True)
    paper = paper_stats_for_researcher(session, r)
    latest = exps[0] if exps else None
    evolution_tree = [
        {
            "id": str(e.id),
            "parent_id": str(e.parent_experiment_id) if e.parent_experiment_id else None,
            "status": e.status,
            "tier": e.validation_tier,
            "family": e.strategy_family,
            "hypothesis": e.hypothesis[:180],
            "metrics": e.validation_metrics,
            "lineage": e.lineage,
        }
        for e in exps
    ]
    return {
        "researcher": {
            "id": str(r.id),
            "provider_slug": r.provider_slug,
            "display_name": r.display_name,
            "enabled": r.enabled,
            "activated_by_user": r.activated_by_user,
            "model_id": r.model_id,
            "memory": memory_context_for_llm(r),
            "objectives": r.objectives,
            "stats": r.stats,
            "current_activity": r.current_activity,
            "discovery_goal": (r.objectives or {}).get("prop_constraints"),
            "latest_hypothesis": latest.hypothesis if latest else None,
            "daily_spend_usd": float(daily),
            "monthly_spend_usd": float(monthly),
            "daily_budget_usd": float(r.daily_budget_usd),
            "monthly_budget_usd": float(r.monthly_budget_usd),
            "remaining_daily_budget_usd": max(0, float(r.daily_budget_usd - daily)),
            "remaining_monthly_budget_usd": max(0, float(r.monthly_budget_usd - monthly)),
            "max_refinement_depth": r.max_refinement_depth,
            "max_child_experiments": r.max_child_experiments,
            "max_backtests_per_cycle": r.max_backtests_per_cycle,
        },
        "forward_paper": paper,
        "active_paper_positions": paper.get("active_paper_positions") or [],
        "cycles": [
            {
                "id": str(c.id),
                "status": c.status,
                "phase": c.phase,
                "detail": c.detail,
                "started_at": c.started_at.isoformat(),
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            }
            for c in cycles
        ],
        "evolution_tree": evolution_tree,
        "experiments": [
            {
                "id": str(e.id),
                "parent_experiment_id": str(e.parent_experiment_id) if e.parent_experiment_id else None,
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