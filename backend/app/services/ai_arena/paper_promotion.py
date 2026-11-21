"""Promote scientifically validated arena strategies to paper scanner (no live orders)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.backtest.dsl import ENTRY_TYPES
from app.models.ai_arena import AiExperiment
from app.models.strategy import StrategyDefinition
from app.services.ai_arena.guardrails import get_or_create_settings
from app.services.paper_book import enroll_strategy

INCREMENTAL_EXCLUDED = frozenset({"video_anchor_bos", "video_liquidity_sweep", "video_combined"})


def incremental_execution_compatible(spec: dict) -> bool:
    etype = (spec.get("entry") or {}).get("type")
    return bool(etype) and etype in ENTRY_TYPES and etype not in INCREMENTAL_EXCLUDED


def try_promote_validated_experiment(session: Session, experiment: AiExperiment) -> dict:
    settings = get_or_create_settings(session)
    if not settings.auto_paper_promotion:
        return {"promoted": False, "reason": "auto_paper_promotion_disabled"}
    if experiment.validation_tier != "validated":
        return {"promoted": False, "reason": "not_validated_tier"}
    if not experiment.strategy_id or not experiment.backtest_run_id:
        return {"promoted": False, "reason": "missing_strategy_or_run"}
    strategy = session.get(StrategyDefinition, experiment.strategy_id)
    if not strategy:
        return {"promoted": False, "reason": "strategy_missing"}
    spec = experiment.specification or {}
    if not incremental_execution_compatible(spec):
        return {"promoted": False, "reason": "not_incremental_compatible"}
    enroll_strategy(session, strategy, experiment.symbol)
    lineage = dict(experiment.lineage or {})
    lineage["paper_promoted"] = True
    experiment.lineage = lineage
    experiment.lifecycle_phase = "forward_paper"
    session.add(experiment)
    return {"promoted": True, "strategy_id": str(strategy.id)}