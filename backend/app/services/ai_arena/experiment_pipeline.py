"""Single arena experiment: DSL validate → scientific validation → persist lineage."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.dsl import validate_spec
from app.models.ai_arena import AiExperiment, AiResearchCycle, AiResearcher
from app.models.backtest import BacktestRun
from app.models.instrument import Instrument
from app.services.ai_arena.fingerprint import spec_fingerprint
from app.services.ai_arena.paper_promotion import try_promote_validated_experiment
from app.services.ai_arena.research_memory import update_memory_from_experiment
from app.services.market_data.data_lineage import assert_genuine_for_backtest
from app.services.market_data.ohlcv_cache import latest_dataset
from app.services.strategy_factory import create_strategy_sync
from app.services.strategy_search import scientifically_validate_spec
from app.services.backtest_runner import execute_backtest_run
from app.util.serde import provisional_reproducibility_id


def duplicate_fingerprint(session: Session, fp: str) -> bool:
    return (
        session.execute(select(AiExperiment.id).where(AiExperiment.spec_fingerprint == fp).limit(1)).scalar_one_or_none()
        is not None
    )


def parent_compare_metrics(parent: AiExperiment, child_metrics: dict) -> dict:
    pm = parent.validation_metrics or {}
    return {
        "parent_net_pnl": pm.get("net_pnl"),
        "child_net_pnl": child_metrics.get("net_pnl"),
        "parent_pf": pm.get("profit_factor"),
        "child_pf": child_metrics.get("profit_factor"),
        "parent_trades": pm.get("trade_count"),
        "child_trades": child_metrics.get("trade_count"),
        "improved_pnl": (child_metrics.get("net_pnl") or 0) > (pm.get("net_pnl") or 0),
    }


def run_spec_experiment(
    session: Session,
    researcher: AiResearcher,
    cycle: AiResearchCycle,
    *,
    spec: dict,
    family: str,
    hypothesis: str,
    reasoning_summary: str,
    parent_experiment_id=None,
    depth: int = 0,
    analysis: dict | None = None,
) -> AiExperiment:
    tf = str(spec.get("timeframe") or "5m")
    fp = spec_fingerprint(spec)
    if duplicate_fingerprint(session, fp):
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            parent_experiment_id=parent_experiment_id,
            lifecycle_phase="duplicate",
            hypothesis=hypothesis,
            reasoning_summary=reasoning_summary,
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=family,
            symbol=str(spec.get("instrument_symbol", "MNQ")).upper(),
            timeframe=tf,
            status="duplicate",
            rejection_reason="Substantially similar spec already researched",
            author_provider_slug=researcher.provider_slug,
            lineage={"depth": depth, "analysis": analysis or {}},
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        session.flush()
        return exp

    errs = validate_spec(spec)
    if errs:
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            parent_experiment_id=parent_experiment_id,
            lifecycle_phase="rejected_dsl",
            hypothesis=hypothesis,
            reasoning_summary=reasoning_summary,
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=family,
            symbol=str(spec.get("instrument_symbol", "MNQ")).upper(),
            timeframe=tf,
            status="rejected",
            rejection_reason="; ".join(errs),
            author_provider_slug=researcher.provider_slug,
            lineage={"depth": depth},
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        session.flush()
        update_memory_from_experiment(researcher, exp)
        return exp

    dataset = latest_dataset(session, spec["instrument_symbol"], tf)
    if not dataset:
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            parent_experiment_id=parent_experiment_id,
            hypothesis=hypothesis,
            reasoning_summary=reasoning_summary,
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=family,
            symbol=str(spec.get("instrument_symbol", "MNQ")).upper(),
            timeframe=tf,
            status="rejected",
            rejection_reason="No historical dataset",
            author_provider_slug=researcher.provider_slug,
            lineage={"depth": depth},
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        session.flush()
        return exp

    meta = dataset.meta or {}
    try:
        if not meta.get("data_lineage"):
            raise ValueError("missing data_lineage")
        assert_genuine_for_backtest(meta)
    except Exception as exc:
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            parent_experiment_id=parent_experiment_id,
            hypothesis=hypothesis,
            reasoning_summary=reasoning_summary,
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=family,
            symbol=str(spec.get("instrument_symbol", "MNQ")).upper(),
            timeframe=tf,
            status="rejected",
            rejection_reason=str(exc)[:300],
            author_provider_slug=researcher.provider_slug,
            lineage={"depth": depth},
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        session.flush()
        return exp

    inst = session.execute(
        select(Instrument).where(Instrument.symbol == spec["instrument_symbol"].upper())
    ).scalar_one_or_none()
    if not inst:
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            parent_experiment_id=parent_experiment_id,
            hypothesis=hypothesis,
            reasoning_summary=reasoning_summary,
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=family,
            symbol=str(spec.get("instrument_symbol", "MNQ")).upper(),
            timeframe=tf,
            status="rejected",
            rejection_reason="Instrument not registered",
            author_provider_slug=researcher.provider_slug,
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        session.flush()
        return exp

    strategy = create_strategy_sync(
        session,
        specification=spec,
        economic_rationale=hypothesis,
        created_by=f"ai_arena:{researcher.provider_slug}",
    )
    validation = scientifically_validate_spec(session, dataset, inst, spec, origin="ai_arena")
    tier = validation.get("validation_tier", "rejected")
    graded = validation.get("metrics") or {}
    summary_ai = validation.get("summary_for_ai") or {}
    metrics = {
        **summary_ai,
        "validation_tier": tier,
        "grade": validation.get("grade"),
        "trade_count": graded.get("trade_count"),
        "net_pnl": graded.get("total_net_profit") or graded.get("net_pnl"),
        "max_drawdown": graded.get("max_drawdown"),
        "profit_factor": graded.get("profit_factor"),
        "oos_passed": summary_ai.get("oos_passed"),
    }
    run = BacktestRun(
        strategy_id=strategy.id,
        strategy_version_id=strategy.current_version_id,
        dataset_id=dataset.id,
        status="queued",
        engine_version="pending",
        reproducibility_id=provisional_reproducibility_id(),
        assumptions={"require_genuine_historical": True},
        parameters={"origin": "ai_arena", "provider": researcher.provider_slug, "validation_tier": tier, "depth": depth},
        metrics=graded,
    )
    session.add(run)
    session.flush()
    try:
        execute_backtest_run(session, run.id)
        session.refresh(run)
    except Exception:
        pass

    if tier == "validated":
        status, lifecycle = "validated", "validation"
        rejection = None
    elif tier == "experimental":
        status, lifecycle = "experimental", "robustness"
        rejection = "Experimental tier — not keeper validated"
    else:
        status, lifecycle = "rejected", "rejected"
        rejection = validation.get("reason") or "Failed research-grade validation"

    lineage = {
        "provider": researcher.provider_slug,
        "model_id": researcher.model_id,
        "family": family,
        "depth": depth,
        "validation_summary": summary_ai,
        "analysis": analysis or {},
        "data_source": str((meta.get("data_lineage") or {}).get("source") or meta.get("source") or ""),
        "market_regime": str((meta.get("data_lineage") or {}).get("regime") or meta.get("regime") or "unspecified"),
    }
    if parent_experiment_id:
        parent = session.get(AiExperiment, parent_experiment_id)
        if parent:
            lineage["parent_comparison"] = parent_compare_metrics(parent, metrics)

    exp = AiExperiment(
        researcher_id=researcher.id,
        cycle_id=cycle.id,
        parent_experiment_id=parent_experiment_id,
        lifecycle_phase=lifecycle,
        hypothesis=hypothesis,
        reasoning_summary=reasoning_summary,
        specification=spec,
        spec_fingerprint=fp,
        strategy_family=family,
        symbol=str(spec.get("instrument_symbol")).upper(),
        timeframe=tf,
        status=status,
        validation_tier=tier,
        validation_report={k: v for k, v in validation.items() if k != "metrics"},
        rejection_reason=rejection,
        backtest_run_id=run.id,
        validation_metrics=metrics,
        strategy_id=strategy.id,
        strategy_version_id=strategy.current_version_id,
        lineage=lineage,
        author_provider_slug=researcher.provider_slug,
        completed_at=datetime.now(UTC),
    )
    session.add(exp)
    session.flush()
    if tier == "validated":
        try_promote_validated_experiment(session, exp)
    update_memory_from_experiment(researcher, exp)
    return exp