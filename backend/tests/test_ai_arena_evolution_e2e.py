"""Deterministic arena evolution workflow — mocked LLM, no API spend."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.ai_arena import AiExperiment, AiResearchCycle, AiResearcher
from app.services.ai_arena.cycle import run_researcher_cycle
from app.services.ai_arena.llm_providers import LlmJsonResult, LlmUsage


def _llm_result(data: dict) -> LlmJsonResult:
    return LlmJsonResult(
        data=data,
        usage=LlmUsage(tokens_in=10, tokens_out=20, cost_usd=0.001, latency_ms=5),
        model="mock",
        provider_slug="openai",
    )


def test_evolution_chain_mocks_provider_and_pipeline():
    researcher = AiResearcher(
        id=uuid4(),
        provider_slug="openai",
        display_name="OpenAI",
        enabled=True,
        activated_by_user=True,
        model_id="mock",
        max_refinement_depth=1,
        max_child_experiments=1,
        max_backtests_per_cycle=3,
    )
    session = MagicMock()
    session.flush = MagicMock()
    session.add = MagicMock()

    hypothesis = {
        "hypothesis": "EMA pullback MNQ",
        "strategy_family": "momentum",
        "instrument_symbol": "MNQ",
        "timeframe": "5m",
        "specification": {
            "name": "MNQ 5m momentum",
            "instrument_symbol": "MNQ",
            "timeframe": "5m",
            "entry": {"type": "ema_crossover", "fast_period": 9, "slow_period": 21},
            "exit": {"stop_ticks": 16, "target_ticks": 24, "session_end_flatten": True},
        },
    }
    analysis = {
        "diagnosis": "weak sample",
        "failure_modes": ["low trades"],
        "improvement_ideas": ["tighten stop"],
        "abandon_family": False,
        "reasoning_summary": "try shorter stop",
    }
    child_spec = {
        "name": "MNQ 5m momentum v2",
        "instrument_symbol": "MNQ",
        "timeframe": "5m",
        "entry": {"type": "ema_crossover", "fast_period": 8, "slow_period": 21},
        "exit": {"stop_ticks": 12, "target_ticks": 20, "session_end_flatten": True},
    }

    provider = MagicMock()
    provider.api_key_configured.return_value = True
    provider.default_model = "mock"
    provider.complete_json.side_effect = [
        _llm_result(hypothesis),
        _llm_result(analysis),
    ]

    root_exp = AiExperiment(
        id=uuid4(),
        researcher_id=researcher.id,
        status="rejected",
        validation_tier="rejected",
        validation_metrics={"trade_count": 8, "net_pnl": -100},
        specification=hypothesis["specification"],
        strategy_family="momentum",
        symbol="MNQ",
        timeframe="5m",
        hypothesis="EMA pullback MNQ",
        lineage={"depth": 0},
    )
    child_exp = AiExperiment(
        id=uuid4(),
        researcher_id=researcher.id,
        parent_experiment_id=root_exp.id,
        status="experimental",
        validation_tier="experimental",
        validation_metrics={"trade_count": 20, "net_pnl": 50},
        specification=child_spec,
        strategy_family="momentum",
        symbol="MNQ",
        timeframe="5m",
        hypothesis="child",
        lineage={"depth": 1},
    )

    patches = [
        patch("app.services.ai_arena.cycle.arena_globally_allowed", return_value=True),
        patch("app.services.ai_arena.cycle.budget_allows", return_value=(True, "")),
        patch("app.services.ai_arena.cycle.cycle_already_running", return_value=False),
        patch("app.services.ai_arena.cycle.recover_stale_cycles", return_value=0),
        patch("app.services.ai_arena.cycle.touch_cycle_heartbeat", return_value=True),
        patch("app.services.ai_arena.cycle.get_provider", return_value=provider),
        patch("app.services.ai_arena.cycle.reserve_llm_budget", return_value=(True, "")),
        patch("app.services.ai_arena.cycle.release_llm_reservation"),
        patch("app.services.ai_arena.cycle.run_spec_experiment", return_value=root_exp),
        patch("app.services.ai_arena.cycle.evolve_after_root", return_value=[child_exp]),
    ]
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        out = run_researcher_cycle(session, researcher, manual=True)

    assert out.get("ok") is True
    assert out.get("experiments") == 2