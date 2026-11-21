"""Build paper slot attribution from arena experiments."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.ai_arena import AiExperiment, AiResearcher
from app.models.market_data import HistoricalDataset
from app.models.backtest import BacktestRun


def attribution_for_experiment(session: Session, experiment: AiExperiment) -> dict:
    researcher = session.get(AiResearcher, experiment.researcher_id)
    run = session.get(BacktestRun, experiment.backtest_run_id) if experiment.backtest_run_id else None
    data_source = (experiment.lineage or {}).get("data_source") or ""
    if run and not data_source:
        ds = session.get(HistoricalDataset, run.dataset_id)
        if ds and ds.meta:
            data_source = str((ds.meta.get("data_lineage") or {}).get("source") or ds.meta.get("source") or "")
    return {
        "ai_provider": experiment.author_provider_slug,
        "model_id": (researcher.model_id if researcher else "") or "",
        "researcher_id": str(experiment.researcher_id),
        "experiment_id": str(experiment.id),
        "strategy_id": str(experiment.strategy_id) if experiment.strategy_id else None,
        "strategy_version_id": str(experiment.strategy_version_id) if experiment.strategy_version_id else None,
        "instrument": experiment.symbol,
        "market_data_source": data_source,
        "validation_tier": experiment.validation_tier,
        "parent_experiment_id": str(experiment.parent_experiment_id) if experiment.parent_experiment_id else None,
    }