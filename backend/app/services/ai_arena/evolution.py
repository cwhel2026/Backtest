"""In-cycle analysis, refinement children, and iteration limits."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.ai_arena import AiExperiment, AiResearchCycle, AiResearcher
from app.services.ai_arena.experiment_pipeline import run_spec_experiment
from app.services.ai_arena.guardrails import release_llm_reservation, reserve_llm_budget
from app.services.ai_arena.llm_providers import get_provider
from app.services.ai_arena.research_memory import memory_context_for_llm
from app.services.ai_search_mutator import propose_search_specs

ANALYSIS_SYSTEM = """Futures quant analyst. Output JSON only:
{
  "diagnosis": "why backtest succeeded or failed (2-4 sentences)",
  "failure_modes": ["..."],
  "improvement_ideas": ["..."],
  "abandon_family": false,
  "reasoning_summary": "short"
}
Do not reference holdout data. Use only metrics supplied (in-sample/OOS/robustness summaries)."""


REFINE_HINT = """Propose refined DSL specifications as children of the parent experiment.
Return JSON: {"rationale": "...", "specifications": [ ... DSL specs ... ]}
Rules: same researcher constraints; meaningful parameter/logic changes vs parent; max specs as requested.
"""


@dataclass
class CycleBudget:
    backtests_remaining: int
    depth_limit: int
    child_limit: int

    @classmethod
    def from_researcher(cls, researcher: AiResearcher) -> CycleBudget:
        return cls(
            backtests_remaining=int(researcher.max_backtests_per_cycle or 6),
            depth_limit=int(researcher.max_refinement_depth or 2),
            child_limit=int(researcher.max_child_experiments or 3),
        )

    def consume_backtest(self) -> bool:
        if self.backtests_remaining <= 0:
            return False
        self.backtests_remaining -= 1
        return True


def _record_usage(session: Session, researcher: AiResearcher, result, call_kind: str) -> None:
    from app.models.ai_arena import AiApiUsage

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


def analyze_experiment(
    session: Session,
    researcher: AiResearcher,
    experiment: AiExperiment,
) -> dict | None:
    provider = get_provider(researcher.provider_slug)
    if not provider.api_key_configured():
        return None
    ok, _ = reserve_llm_budget(session, researcher)
    if not ok:
        return None
    metrics = experiment.validation_metrics or {}
    user = json.dumps(
        {
            "hypothesis": experiment.hypothesis,
            "family": experiment.strategy_family,
            "status": experiment.status,
            "tier": experiment.validation_tier,
            "rejection": experiment.rejection_reason,
            "metrics_for_analysis": metrics,
            "entry_type": (experiment.specification or {}).get("entry", {}).get("type"),
            "memory": memory_context_for_llm(researcher),
        },
        default=str,
    )
    try:
        result = provider.complete_json(system=ANALYSIS_SYSTEM, user=user, model=researcher.model_id or None)
        _record_usage(session, researcher, result, "analysis")
        return result.data
    except Exception:
        return None
    finally:
        release_llm_reservation()


def run_refinement_children(
    session: Session,
    researcher: AiResearcher,
    cycle: AiResearchCycle,
    parent: AiExperiment,
    analysis: dict,
    budget: CycleBudget,
    *,
    touch_heartbeat=None,
) -> list[AiExperiment]:
    if analysis.get("abandon_family"):
        return []
    provider = get_provider(researcher.provider_slug)
    if not provider.api_key_configured():
        return []
    ok, _ = reserve_llm_budget(session, researcher)
    if not ok:
        return []
    parent_spec = parent.specification or {}
    symbol = parent.symbol
    memory_blob = json.dumps(
        {
            "analysis": analysis,
            "parent_hypothesis": parent.hypothesis,
            "parent_metrics": parent.validation_metrics,
            "parent_spec_summary": {
                "entry": parent_spec.get("entry"),
                "exit": parent_spec.get("exit"),
                "filters": parent_spec.get("filters"),
            },
            "researcher_memory": memory_context_for_llm(researcher),
        },
        default=str,
    )
    children: list[AiExperiment] = []
    try:
        rationale, specs = propose_search_specs(
            symbol,
            memory_blob + "\n" + REFINE_HINT,
            max_specs=budget.child_limit,
            provider_slug=researcher.provider_slug,
            model=researcher.model_id or None,
            arena_provider_only=True,
        )
        for spec in specs[: budget.child_limit]:
            if not budget.consume_backtest():
                break
            if touch_heartbeat:
                touch_heartbeat()
            reasoning = f"{rationale} · child of {parent.id}"[:500]
            child = run_spec_experiment(
                session,
                researcher,
                cycle,
                spec=spec,
                family=parent.strategy_family,
                hypothesis=spec.get("name") or parent.hypothesis,
                reasoning_summary=reasoning,
                parent_experiment_id=parent.id,
                depth=int((parent.lineage or {}).get("depth", 0)) + 1,
                analysis=analysis,
            )
            children.append(child)
            if child.validation_tier == "validated":
                break
    finally:
        release_llm_reservation()
    return children


def evolve_after_root(
    session: Session,
    researcher: AiResearcher,
    cycle: AiResearchCycle,
    root: AiExperiment,
    budget: CycleBudget,
    *,
    touch_heartbeat=None,
) -> list[AiExperiment]:
    """Depth-limited refinement chain from a root experiment."""
    if root.validation_tier == "validated":
        return []
    all_children: list[AiExperiment] = []
    current = root
    depth = 0
    while depth < budget.depth_limit and budget.backtests_remaining > 0:
        researcher.current_activity = f"Analyzing experiment {str(current.id)[:8]} for refinements"
        analysis = analyze_experiment(session, researcher, current)
        if not analysis:
            break
        current.reasoning_summary = (current.reasoning_summary or "") + " | " + str(analysis.get("reasoning_summary", ""))[:200]
        session.add(current)
        if touch_heartbeat:
            touch_heartbeat()
        children = run_refinement_children(session, researcher, cycle, current, analysis, budget, touch_heartbeat=touch_heartbeat)
        if not children:
            break
        all_children.extend(children)
        if any(c.validation_tier == "validated" for c in children):
            break
        current = children[0]
        depth += 1
    return all_children