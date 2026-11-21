"""Cross-AI strategy critique — advisory only, not validation."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.ai_arena import AiExperiment, AiStrategyCritique, AiResearcher
from app.services.ai_arena.llm_providers import get_provider

CRITIQUE_SYSTEM = """You critique a futures strategy specification for logical errors, overfitting risk,
unrealistic assumptions, and execution issues. Output JSON: {
  "issues": [string], "overfitting_risk": "low|medium|high", "execution_concerns": [string], "summary": string
}. Critique does not approve or reject — statistical backtests decide eligibility."""


def request_cross_critique(
    session: Session,
    *,
    experiment: AiExperiment,
    critic: AiResearcher,
) -> AiStrategyCritique | None:
    if not critic.enabled or not critic.activated_by_user:
        return None
    provider = get_provider(critic.provider_slug)
    if not provider.api_key_configured():
        return None
    model = critic.model_id or provider.default_model
    user = json.dumps(
        {
            "author": experiment.author_provider_slug,
            "family": experiment.strategy_family,
            "specification": experiment.specification,
            "validation_metrics": experiment.validation_metrics,
        },
        default=str,
    )
    try:
        result = provider.complete_json(system=CRITIQUE_SYSTEM, user=user, model=model)
    except Exception:
        return None
    row = AiStrategyCritique(
        experiment_id=experiment.id,
        critic_provider_slug=critic.provider_slug,
        author_provider_slug=experiment.author_provider_slug,
        critique=result.data,
    )
    session.add(row)
    return row