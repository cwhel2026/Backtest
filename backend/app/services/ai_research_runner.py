"""Celery-side AI research: strategy creation + optional backtest queue."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.backtest import BacktestRun
from app.models.enums import ResearchJobKind
from app.models.research import ResearchJob
from app.models.strategy import StrategyDefinition
from app.services.ai_research import generate_hypothesis_and_spec
from app.services.strategy_factory import create_strategy_sync


def run_ai_hypothesis_job(session: Session, job: ResearchJob) -> tuple[StrategyDefinition, str | None]:
    payload = job.payload or {}
    symbol = payload.get("instrument_symbol", "MES")
    timeframe = payload.get("timeframe", "5m")
    prompt = payload.get("prompt", "")
    actor = payload.get("actor", "ai_worker")
    dataset_id = payload.get("dataset_id")

    rationale, spec = generate_hypothesis_and_spec(symbol, timeframe, prompt)

    from app.core.config import get_settings

    created_by = "openai" if get_settings().ai_configured else "heuristic"

    strategy = create_strategy_sync(
        session,
        specification=spec,
        economic_rationale=rationale,
        created_by=created_by,
    )

    job.payload = {**payload, "strategy_id": str(strategy.id), "generation_mode": created_by}

    backtest_run_id: str | None = None
    if dataset_id:
        run = BacktestRun(
            strategy_id=strategy.id,
            strategy_version_id=strategy.current_version_id,
            dataset_id=uuid.UUID(dataset_id),
            status="queued",
            engine_version="pending",
            reproducibility_id="pending",
            assumptions={},
            parameters={},
        )
        session.add(run)
        session.flush()
        backtest_run_id = str(run.id)
        job.payload["backtest_run_id"] = backtest_run_id

    return strategy, backtest_run_id


def count_ai_jobs_today(session: Session) -> int:
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    q = select(func.count()).select_from(ResearchJob).where(
        ResearchJob.kind == ResearchJobKind.AI_HYPOTHESIS,
        ResearchJob.created_at >= day_start,
    )
    return session.execute(q).scalar_one()