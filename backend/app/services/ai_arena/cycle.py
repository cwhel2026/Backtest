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


def _experiment_shell(
    researcher: AiResearcher,
    cycle: AiResearchCycle,
    payload: dict,
    spec: dict,
    fp: str,
    family: str,
    tf: str,
    reasoning_summary: str,
    *,
    status: str,
    reason: str,
    strategy_id=None,
) -> AiExperiment:
    return AiExperiment(
        researcher_id=researcher.id,
        cycle_id=cycle.id,
        hypothesis=str(payload.get("hypothesis") or ""),
        reasoning_summary=reasoning_summary,
        specification=spec,
        spec_fingerprint=fp,
        strategy_family=str(payload.get("strategy_family") or family),
        symbol=str(spec.get("instrument_symbol")).upper(),
        timeframe=str(spec.get("timeframe") or tf),
        status=status,
        rejection_reason=reason,
        strategy_id=strategy_id,
        author_provider_slug=researcher.provider_slug,
        completed_at=datetime.now(UTC),
    )


def _duplicate_exists(session: Session, fp: str) -> bool:
    return (
        session.execute(select(func.count()).select_from(AiExperiment).where(AiExperiment.spec_fingerprint == fp)).scalar_one()
        or 0
    ) > 0


def run_researcher_cycle(session: Session, researcher: AiResearcher, *, manual: bool = False) -> dict:
    from app.services.ai_arena.guardrails import arena_globally_allowed

    if not arena_globally_allowed(session):
        return {"skipped": True, "reason": "global_guardrail"}
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
    family = random.choice(STRATEGY_FAMILIES)
    researcher.current_activity = f"Generating {family} hypothesis for {symbol}"
    model = researcher.model_id or provider.default_model
    from app.services.ai_arena.guardrails import release_llm_reservation, reserve_llm_budget

    ok_reserve, reserve_reason = reserve_llm_budget(session, researcher)
    if not ok_reserve:
        cycle.status = "skipped"
        cycle.error = reserve_reason
        cycle.completed_at = datetime.now(UTC)
        return {"skipped": True, "reason": reserve_reason}
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
    finally:
        release_llm_reservation()

    payload = result.data
    reasoning_summary = str(payload.get("hypothesis") or payload.get("rationale") or "")
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

    cycle.phase = "scientific_validation"
    researcher.current_activity = "Running research-grade validation (OOS, walk-forward, holdout)"
    from app.models.instrument import Instrument
    from app.services.strategy_search import scientifically_validate_spec
    from app.services.backtest_runner import execute_backtest_run

    rationale = reasoning_summary or f"AI arena {family}"
    inst = session.execute(
        select(Instrument).where(Instrument.symbol == spec["instrument_symbol"].upper())
    ).scalar_one_or_none()
    if not inst:
        exp = _experiment_shell(
            researcher,
            cycle,
            payload,
            spec,
            fp,
            family,
            tf,
            reasoning_summary,
            status="rejected",
            reason="Instrument not registered",
        )
        session.add(exp)
        cycle.status = "completed"
        cycle.phase = "no_instrument"
        cycle.completed_at = datetime.now(UTC)
        return {"ok": True, "experiment_id": str(exp.id), "status": "rejected"}

    try:
        strategy = create_strategy_sync(
            session,
            specification=spec,
            economic_rationale=rationale,
            created_by=f"ai_arena:{researcher.provider_slug}",
        )
        validation = scientifically_validate_spec(session, dataset, inst, spec, origin="ai_arena")
    except Exception as exc:
        exp = _experiment_shell(
            researcher,
            cycle,
            payload,
            spec,
            fp,
            family,
            tf,
            reasoning_summary,
            status="failed_validation",
            reason=str(exc)[:400],
            strategy_id=None,
        )
        session.add(exp)
        cycle.status = "failed"
        cycle.error = str(exc)[:400]
        cycle.completed_at = datetime.now(UTC)
        return {"ok": False, "error": str(exc)}

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
        parameters={"origin": "ai_arena", "provider": researcher.provider_slug, "validation_tier": tier},
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
        status = "validated"
        rejection = None
        lifecycle = "validation"
    elif tier == "experimental":
        status = "experimental"
        rejection = "Passed simplified historical gates only — labeled experimental until full keeper grade"
        lifecycle = "robustness"
    else:
        status = "rejected"
        rejection = validation.get("reason") or "Failed research-grade validation"
        lifecycle = "rejected"

    exp = AiExperiment(
        researcher_id=researcher.id,
        cycle_id=cycle.id,
        hypothesis=str(payload.get("hypothesis") or ""),
        reasoning_summary=reasoning_summary,
        lifecycle_phase=lifecycle,
        specification=spec,
        spec_fingerprint=fp,
        strategy_family=str(payload.get("strategy_family") or family),
        symbol=str(spec.get("instrument_symbol")).upper(),
        timeframe=str(spec.get("timeframe") or tf),
        status=status,
        validation_tier=tier,
        validation_report={k: v for k, v in validation.items() if k != "metrics"},
        rejection_reason=rejection,
        backtest_run_id=run.id,
        validation_metrics=metrics,
        strategy_id=strategy.id,
        strategy_version_id=strategy.current_version_id,
        lineage={
            "provider": researcher.provider_slug,
            "family": family,
            "dsl_fingerprint": fp,
            "validation_summary": summary_ai,
        },
        author_provider_slug=researcher.provider_slug,
        completed_at=datetime.now(UTC),
    )
    session.add(exp)
    if tier == "validated":
        from app.services.ai_arena.paper_promotion import try_promote_validated_experiment

        try_promote_validated_experiment(session, exp)

    mem = dict(researcher.memory or {})
    mem.setdefault("experiments", [])
    mem.setdefault("failed_families", [])
    if status == "rejected":
        fam = exp.strategy_family
        fails = [f for f in (mem.get("failed_families") or []) if f != fam]
        fails.append(fam)
        mem["failed_families"] = fails[-20:]
    mem["experiments"] = (mem.get("experiments") or [])[-49:] + [
        {
            "id": str(exp.id),
            "status": exp.status,
            "tier": tier,
            "family": exp.strategy_family,
            "metrics": metrics,
        }
    ]
    researcher.memory = mem
    cycle.status = "completed"
    cycle.phase = lifecycle
    cycle.detail = {"experiment_id": str(exp.id), "metrics": metrics, "validation_tier": tier, "manual": manual}
    cycle.completed_at = datetime.now(UTC)
    researcher.last_success_at = datetime.now(UTC)
    researcher.current_activity = "Idle between cycles"
    _bump_stats(researcher, rejected=status == "rejected", validated=status == "validated", experimental=status == "experimental")
    return {"ok": True, "experiment_id": str(exp.id), "status": exp.status, "validation_tier": tier, "metrics": metrics}


def _bump_stats(
    researcher: AiResearcher,
    *,
    rejected: bool = False,
    validated: bool = False,
    experimental: bool = False,
) -> None:
    st = dict(researcher.stats or {})
    st["cycles"] = int(st.get("cycles") or 0) + 1
    if rejected:
        st["rejected"] = int(st.get("rejected") or 0) + 1
    if validated:
        st["validated"] = int(st.get("validated") or 0) + 1
    if experimental:
        st["experimental"] = int(st.get("experimental") or 0) + 1
    st["generated"] = int(st.get("generated") or 0) + 1
    st["tested"] = int(st.get("tested") or 0) + 1
    researcher.stats = st