"""Autonomous per-researcher cycle — DSL only, engine validates."""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest.dsl import validate_spec
from app.models.ai_arena import AiApiUsage, AiExperiment, AiResearchCycle, AiResearcher
from app.services.ai_arena.budget import budget_allows
from app.services.ai_arena.fingerprint import spec_fingerprint
from app.services.ai_arena.llm_providers import get_provider
from app.services.ai_arena.research_context import market_stats_for_symbol, researcher_memory_summary
from app.services.market_data.ohlcv_cache import latest_dataset
from app.services.market_data.data_lineage import assert_genuine_for_backtest
from app.services.strategy_factory import create_strategy_sync
from app.models.backtest import BacktestRun
from app.util.serde import provisional_reproducibility_id

ARENA_SYMBOLS = ("MNQ", "MES", "MGC")
STRATEGY_FAMILIES = (
    "momentum",
    "mean_reversion",
    "liquidity_sweep",
    "trend_following",
    "breakout",
    "volatility",
    "volume",
    "market_structure",
)

HYPOTHESIS_SYSTEM = """You are an independent futures quant researcher for CME micro contracts (MNQ, MES, MGC).
Design intraday strategies under prop-firm risk limits. Output JSON only with keys:
hypothesis (string), strategy_family (one of the allowed families), instrument_symbol, timeframe (5m or 1m),
specification (object matching PROP EDGE DSL with entry.type, exit, filters).
Do not include executable code. Do not claim profitability without backtest evidence.
Avoid duplicates of recent failed families listed in context."""


def _record_usage(session: Session, researcher: AiResearcher, result, call_kind: str) -> None:
    session.add(
        AiApiUsage(
            researcher_id=researcher.id,
            provider_slug=researcher.provider_slug,
            model_id=result.model,
            call_kind=call_kind,
            tokens_in=result.usage.tokens_in,
            tokens_out=result.usage.tokens_out,
            cost_usd=result.usage.cost_usd,
            latency_ms=result.usage.latency_ms,
            success=True,
        )
    )


def _duplicate_exists(session: Session, fp: str) -> bool:
    return (
        session.execute(select(func.count()).select_from(AiExperiment).where(AiExperiment.spec_fingerprint == fp)).scalar_one()
        or 0
    ) > 0


def run_researcher_cycle(session: Session, researcher: AiResearcher, *, manual: bool = False) -> dict:
    if not researcher.enabled or not researcher.activated_by_user:
        return {"skipped": True, "reason": "researcher_disabled"}
    ok, reason = budget_allows(session, researcher)
    if not ok:
        return {"skipped": True, "reason": reason}
    provider = get_provider(researcher.provider_slug)
    if not provider.api_key_configured():
        researcher.connection_status = "unconfigured"
        return {"skipped": True, "reason": "api_key_missing"}

    cycle = AiResearchCycle(researcher_id=researcher.id, status="running", phase="context")
    session.add(cycle)
    researcher.current_activity = "Reviewing market statistics and memory"
    researcher.last_cycle_at = datetime.now(UTC)
    session.flush()

    symbol = random.choice(ARENA_SYMBOLS)
    tf = random.choice(("5m", "1m"))
    stats = market_stats_for_symbol(session, symbol, tf)
    memory = researcher_memory_summary(session, researcher.id)
    memory_block = json.dumps({"market": stats, "memory": memory, "researcher_objectives": researcher.objectives}, default=str)

    cycle.phase = "hypothesis"
    researcher.current_activity = f"Generating {family} hypothesis for {symbol}"
    model = researcher.model_id or provider.default_model
    family = random.choice(STRATEGY_FAMILIES)
    user = (
        f"Strategy family to explore: {family}. Context:\n{memory_block}\n"
        f"Pick symbol near {symbol} and timeframe {tf}. Include category {family} in specification."
    )
    try:
        result = provider.complete_json(system=HYPOTHESIS_SYSTEM, user=user, model=model)
        _record_usage(session, researcher, result, "hypothesis")
        researcher.connection_status = "connected"
    except Exception as exc:
        researcher.connection_status = "error"
        researcher.last_connection_error = str(exc)[:400]
        cycle.status = "failed"
        cycle.error = str(exc)[:500]
        cycle.completed_at = datetime.now(UTC)
        session.add(
            AiApiUsage(
                researcher_id=researcher.id,
                provider_slug=researcher.provider_slug,
                model_id=model,
                call_kind="hypothesis",
                success=False,
                error=str(exc)[:400],
            )
        )
        return {"ok": False, "error": str(exc)}

    payload = result.data
    spec = payload.get("specification") or payload
    if not isinstance(spec, dict):
        cycle.status = "failed"
        cycle.error = "Invalid specification type"
        return {"ok": False, "error": cycle.error}

    spec.setdefault("instrument_symbol", payload.get("instrument_symbol") or symbol)
    spec.setdefault("timeframe", payload.get("timeframe") or tf)
    spec.setdefault("category", payload.get("strategy_family") or family)
    spec.setdefault("name", f"{spec.get('instrument_symbol')} {tf} {family}".replace("_", " "))
    spec.setdefault("session", {"allowed": ["RTH"], "timezone": "America/Chicago"})
    spec.setdefault("risk", {"dollar_risk_per_trade": 75, "max_contracts": 2})
    exit_s = spec.get("exit") or {}
    exit_s.setdefault("stop_ticks", 20)
    exit_s.setdefault("target_ticks", 32)
    exit_s.setdefault("session_end_flatten", True)
    spec["exit"] = exit_s

    errs = validate_spec(spec)
    if errs:
        err = "; ".join(errs)
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            hypothesis=str(payload.get("hypothesis") or ""),
            specification=spec,
            spec_fingerprint=spec_fingerprint(spec),
            strategy_family=str(payload.get("strategy_family") or family),
            symbol=str(spec.get("instrument_symbol")).upper(),
            timeframe=str(spec.get("timeframe") or tf),
            status="rejected",
            rejection_reason=f"DSL validation: {err}",
            author_provider_slug=researcher.provider_slug,
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        cycle.status = "completed"
        cycle.phase = "rejected_dsl"
        cycle.completed_at = datetime.now(UTC)
        _bump_stats(researcher, rejected=True)
        return {"ok": True, "experiment_id": str(exp.id), "status": "rejected", "reason": err}

    fp = spec_fingerprint(spec)
    if _duplicate_exists(session, fp):
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            hypothesis=str(payload.get("hypothesis") or ""),
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=str(payload.get("strategy_family") or family),
            symbol=str(spec.get("instrument_symbol")).upper(),
            timeframe=str(spec.get("timeframe") or tf),
            status="duplicate",
            rejection_reason="Substantially similar spec already researched",
            author_provider_slug=researcher.provider_slug,
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        cycle.status = "completed"
        cycle.phase = "duplicate"
        cycle.completed_at = datetime.now(UTC)
        return {"ok": True, "experiment_id": str(exp.id), "status": "duplicate"}

    dataset = latest_dataset(session, spec["instrument_symbol"], spec.get("timeframe") or tf)
    if not dataset:
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            hypothesis=str(payload.get("hypothesis") or ""),
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=str(payload.get("strategy_family") or family),
            symbol=str(spec.get("instrument_symbol")).upper(),
            timeframe=str(spec.get("timeframe") or tf),
            status="rejected",
            rejection_reason="No historical dataset for backtest",
            author_provider_slug=researcher.provider_slug,
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        cycle.status = "completed"
        cycle.phase = "no_data"
        cycle.completed_at = datetime.now(UTC)
        return {"ok": True, "experiment_id": str(exp.id), "status": "rejected", "reason": "no_dataset"}

    meta = dataset.meta or {}
    if not meta.get("data_lineage"):
        reason = "Dataset missing data_lineage — genuine backtest blocked"
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            hypothesis=str(payload.get("hypothesis") or ""),
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=str(payload.get("strategy_family") or family),
            symbol=str(spec.get("instrument_symbol")).upper(),
            timeframe=str(spec.get("timeframe") or tf),
            status="rejected",
            rejection_reason=reason,
            author_provider_slug=researcher.provider_slug,
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        cycle.status = "completed"
        cycle.phase = "ineligible_data"
        cycle.completed_at = datetime.now(UTC)
        return {"ok": True, "experiment_id": str(exp.id), "status": "rejected", "reason": reason}
    try:
        assert_genuine_for_backtest(meta)
    except Exception as exc:
        reason = str(exc)[:300]
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            hypothesis=str(payload.get("hypothesis") or ""),
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=str(payload.get("strategy_family") or family),
            symbol=str(spec.get("instrument_symbol")).upper(),
            timeframe=str(spec.get("timeframe") or tf),
            status="rejected",
            rejection_reason=reason,
            author_provider_slug=researcher.provider_slug,
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        cycle.status = "completed"
        cycle.phase = "ineligible_data"
        cycle.completed_at = datetime.now(UTC)
        return {"ok": True, "experiment_id": str(exp.id), "status": "rejected", "reason": reason}

    cycle.phase = "backtest"
    researcher.current_activity = "Running genuine historical backtest"
    from app.services.backtest_runner import execute_backtest_run

    rationale = str(payload.get("hypothesis") or f"AI arena {family}")
    try:
        strategy = create_strategy_sync(
            session,
            specification=spec,
            economic_rationale=rationale,
            created_by=f"ai_arena:{researcher.provider_slug}",
        )
        run = BacktestRun(
            strategy_id=strategy.id,
            strategy_version_id=strategy.current_version_id,
            dataset_id=dataset.id,
            status="queued",
            engine_version="pending",
            reproducibility_id=provisional_reproducibility_id(),
            assumptions={"require_genuine_historical": True},
            parameters={"origin": "ai_arena", "provider": researcher.provider_slug, "family": family},
        )
        session.add(run)
        session.flush()
        execute_backtest_run(session, run.id)
        session.refresh(run)
        bt = run
    except Exception as exc:
        exp = AiExperiment(
            researcher_id=researcher.id,
            cycle_id=cycle.id,
            hypothesis=str(payload.get("hypothesis") or ""),
            specification=spec,
            spec_fingerprint=fp,
            strategy_family=str(payload.get("strategy_family") or family),
            symbol=str(spec.get("instrument_symbol")).upper(),
            timeframe=str(spec.get("timeframe") or tf),
            status="failed_validation",
            rejection_reason=str(exc)[:400],
            author_provider_slug=researcher.provider_slug,
            completed_at=datetime.now(UTC),
        )
        session.add(exp)
        cycle.status = "failed"
        cycle.error = str(exc)[:400]
        cycle.completed_at = datetime.now(UTC)
        return {"ok": False, "error": str(exc)}

    m = bt.metrics or {}
    trade_count = int(m.get("trade_count") or 0)
    net_pnl = float(m.get("net_pnl") or 0)
    max_dd = float(m.get("max_drawdown") or 0)
    win_rate = m.get("win_rate")
    metrics = {
        "trade_count": trade_count,
        "net_pnl": net_pnl,
        "win_rate": float(win_rate) if win_rate is not None else None,
        "max_drawdown": max_dd,
        "sharpe": float(m.get("sharpe")) if m.get("sharpe") is not None else None,
        "backtest_status": bt.status,
    }
    validated = bt.status == "completed" and trade_count >= 15 and net_pnl > 0 and max_dd < 5000
    exp = AiExperiment(
        researcher_id=researcher.id,
        cycle_id=cycle.id,
        hypothesis=str(payload.get("hypothesis") or ""),
        specification=spec,
        spec_fingerprint=fp,
        strategy_family=str(payload.get("strategy_family") or family),
        symbol=str(spec.get("instrument_symbol")).upper(),
        timeframe=str(spec.get("timeframe") or tf),
        status="validated" if validated else "rejected",
        rejection_reason=None if validated else "Did not meet arena validation gates (sample size, pnl, drawdown)",
        backtest_run_id=run.id,
        validation_metrics=metrics,
        author_provider_slug=researcher.provider_slug,
        completed_at=datetime.now(UTC),
    )
    session.add(exp)
    mem = dict(researcher.memory or {})
    mem.setdefault("experiments", [])
    mem["experiments"] = (mem.get("experiments") or [])[-49:] + [
        {"id": str(exp.id), "status": exp.status, "family": exp.strategy_family, "metrics": metrics}
    ]
    researcher.memory = mem
    cycle.status = "completed"
    cycle.phase = "validated" if validated else "rejected_metrics"
    cycle.detail = {"experiment_id": str(exp.id), "metrics": metrics, "manual": manual}
    cycle.completed_at = datetime.now(UTC)
    researcher.last_success_at = datetime.now(UTC)
    researcher.current_activity = "Idle between cycles"
    _bump_stats(researcher, rejected=not validated, validated=validated)
    return {"ok": True, "experiment_id": str(exp.id), "status": exp.status, "metrics": metrics}


def _bump_stats(researcher: AiResearcher, *, rejected: bool = False, validated: bool = False) -> None:
    st = dict(researcher.stats or {})
    st["cycles"] = int(st.get("cycles") or 0) + 1
    if rejected:
        st["rejected"] = int(st.get("rejected") or 0) + 1
    if validated:
        st["validated"] = int(st.get("validated") or 0) + 1
    st["generated"] = int(st.get("generated") or 0) + 1
    researcher.stats = st