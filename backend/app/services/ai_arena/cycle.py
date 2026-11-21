"""Autonomous per-researcher cycle — hypothesis, validation, in-cycle evolution."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.ai_arena import AiApiUsage, AiResearchCycle, AiResearcher
from app.services.ai_arena.budget import budget_allows
from app.services.ai_arena.cycle_recovery import (
    cycle_already_running,
    mint_worker_token,
    recover_stale_cycles,
    touch_cycle_heartbeat,
)
from app.services.ai_arena.evolution import CycleBudget, evolve_after_root
from app.services.ai_arena.experiment_pipeline import run_spec_experiment
from app.services.ai_arena.guardrails import arena_globally_allowed, release_llm_reservation, reserve_llm_budget
from app.services.ai_arena.llm_providers import get_provider
from app.services.ai_arena.research_context import market_stats_for_symbol
from app.services.ai_arena.research_memory import memory_context_for_llm

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
Do not include executable code. Avoid families listed in failures_to_avoid. Explore diverse hypotheses when families are stale."""


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


def _bump_stats(researcher: AiResearcher, experiments: list) -> None:
    st = dict(researcher.stats or {})
    st["cycles"] = int(st.get("cycles") or 0) + 1
    for exp in experiments:
        st["generated"] = int(st.get("generated") or 0) + 1
        st["tested"] = int(st.get("tested") or 0) + 1
        if exp.parent_experiment_id:
            st["refinements"] = int(st.get("refinements") or 0) + 1
        if exp.status == "rejected":
            st["rejected"] = int(st.get("rejected") or 0) + 1
        if exp.status == "validated":
            st["validated"] = int(st.get("validated") or 0) + 1
        if exp.status == "experimental":
            st["experimental"] = int(st.get("experimental") or 0) + 1
    families = set(st.get("families_explored") or [])
    for exp in experiments:
        if exp.strategy_family:
            families.add(exp.strategy_family)
    st["families_explored"] = list(families)[-20:]
    researcher.stats = st


def run_researcher_cycle(session: Session, researcher: AiResearcher, *, manual: bool = False) -> dict:
    if not arena_globally_allowed(session):
        return {"skipped": True, "reason": "global_guardrail"}
    if not researcher.enabled or not researcher.activated_by_user:
        return {"skipped": True, "reason": "researcher_disabled"}
    ok, reason = budget_allows(session, researcher)
    if not ok:
        return {"skipped": True, "reason": reason}

    recover_stale_cycles(session, researcher.id)
    if cycle_already_running(session, researcher.id):
        return {"skipped": True, "reason": "cycle_already_running"}

    provider = get_provider(researcher.provider_slug)
    if not provider.api_key_configured():
        researcher.connection_status = "unconfigured"
        return {"skipped": True, "reason": "api_key_missing"}

    cycle = AiResearchCycle(researcher_id=researcher.id, status="running", phase="context")
    session.add(cycle)
    session.flush()
    token = mint_worker_token(cycle)

    def heartbeat() -> None:
        touch_cycle_heartbeat(session, cycle.id, token)

    researcher.current_activity = "Reviewing structured memory and market context"
    researcher.last_cycle_at = datetime.now(UTC)
    session.flush()

    symbol = random.choice(ARENA_SYMBOLS)
    tf = random.choice(("5m", "1m"))
    family = random.choice(STRATEGY_FAMILIES)
    mem = memory_context_for_llm(researcher)
    avoid = mem.get("families_to_avoid") or []
    if family in avoid and len(STRATEGY_FAMILIES) > 1:
        family = random.choice([f for f in STRATEGY_FAMILIES if f not in avoid[:3]] or STRATEGY_FAMILIES)

    stats = market_stats_for_symbol(session, symbol, tf)
    memory_block = json.dumps(
        {"market": stats, "researcher_memory": mem, "failures_to_avoid": avoid, "objectives": researcher.objectives},
        default=str,
    )

    cycle.phase = "hypothesis"
    researcher.current_activity = f"Generating {family} hypothesis for {symbol}"
    model = researcher.model_id or provider.default_model

    ok_reserve, reserve_reason = reserve_llm_budget(session, researcher)
    if not ok_reserve:
        cycle.status = "skipped"
        cycle.error = reserve_reason
        cycle.completed_at = datetime.now(UTC)
        return {"skipped": True, "reason": reserve_reason}

    user = (
        f"Strategy family: {family}. Context:\n{memory_block}\n"
        f"Target symbol near {symbol}, timeframe {tf}."
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
        cycle.completed_at = datetime.now(UTC)
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
    family = str(payload.get("strategy_family") or family)

    budget = CycleBudget.from_researcher(researcher)
    if not budget.consume_backtest():
        cycle.status = "skipped"
        cycle.error = "backtest budget exhausted"
        cycle.completed_at = datetime.now(UTC)
        return {"skipped": True, "reason": "max_backtests_per_cycle"}

    heartbeat()
    researcher.current_activity = "Backtesting root hypothesis"
    root = run_spec_experiment(
        session,
        researcher,
        cycle,
        spec=spec,
        family=family,
        hypothesis=str(payload.get("hypothesis") or ""),
        reasoning_summary=reasoning_summary,
        parent_experiment_id=None,
        depth=0,
    )
    experiments = [root]

    if root.validation_tier != "validated" and budget.backtests_remaining > 0:
        cycle.phase = "evolution"
        researcher.current_activity = "Refining strategy based on backtest analysis"
        heartbeat()
        children = evolve_after_root(session, researcher, cycle, root, budget, touch_heartbeat=heartbeat)
        experiments.extend(children)

    _bump_stats(researcher, experiments)
    cycle.status = "completed"
    cycle.phase = "evolution" if len(experiments) > 1 else root.lifecycle_phase
    cycle.detail = {
        "experiment_ids": [str(e.id) for e in experiments],
        "root_id": str(root.id),
        "validated": any(e.validation_tier == "validated" for e in experiments),
        "manual": manual,
    }
    cycle.completed_at = datetime.now(UTC)
    researcher.last_success_at = datetime.now(UTC)
    researcher.current_activity = "Idle between cycles"
    best = next((e for e in experiments if e.validation_tier == "validated"), root)
    return {
        "ok": True,
        "experiment_id": str(best.id),
        "experiments": len(experiments),
        "status": best.status,
        "validation_tier": best.validation_tier,
    }