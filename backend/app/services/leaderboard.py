"""Ranked backtest leaderboard with strategy context."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.backtest import BacktestRun
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.strategy import StrategyDefinition, StrategyVersion
from app.services.prop_screen import (
    format_metric_display,
    is_profitable_backtest,
    prop_gate_miss,
    prop_readiness_score,
    rank_score,
)
from app.services.result_card import build_test_meta, risk_profile, sample_window


def _entry(
    run: BacktestRun,
    strategy: StrategyDefinition,
    instrument: Instrument,
    dataset: HistoricalDataset,
    spec: dict | None,
    *,
    profitable_only: bool,
) -> dict | None:
    metrics = run.metrics or {}
    tf = dataset.timeframe or strategy.timeframe
    params = run.parameters or {}
    origin = str(params.get("origin") or ("reverse" if strategy.category.startswith("reversed_") else "deep"))
    reverse = origin == "reverse"
    passes = is_profitable_backtest(metrics, reverse=reverse, timeframe=tf)
    if profitable_only and not passes:
        return None
    display = format_metric_display(metrics)
    return {
        "run_id": str(run.id),
        "strategy_id": str(strategy.id),
        "strategy_name": strategy.name,
        "symbol": instrument.symbol,
        "category": strategy.category,
        "timeframe": tf,
        "entry_type": (metrics.get("entry_type") if isinstance(metrics.get("entry_type"), str) else None)
        or _entry_type_from_strategy(strategy),
        "origin": origin,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "tested_at": run.completed_at.isoformat() if run.completed_at else None,
        "prop_ready_score": prop_readiness_score(metrics, timeframe=tf),
        "passes_prop_screen": passes,
        "gate_miss": None if passes else prop_gate_miss(metrics, reverse=reverse, timeframe=tf),
        "metrics": display,
        "sample": sample_window(
            coverage_start=dataset.coverage_start,
            coverage_end=dataset.coverage_end,
            row_count=int(dataset.row_count or 0),
            timeframe=tf,
        ),
        "risk": risk_profile(
            spec,
            metrics,
            tick_value=float(instrument.tick_value or 0),
        ),
        "tests": build_test_meta(tested_at=run.completed_at, params=params, metrics=metrics),
        "rank_score": rank_score(metrics),
    }


def _entry_type_from_strategy(strategy: StrategyDefinition) -> str:
    return strategy.category.replace("_", " ")


async def leaderboard_entries_async(
    session: AsyncSession,
    *,
    limit: int = 15,
    profitable_only: bool = True,
) -> list[dict]:
    result = await session.execute(
        select(BacktestRun, StrategyDefinition, Instrument, HistoricalDataset)
        .join(StrategyDefinition, BacktestRun.strategy_id == StrategyDefinition.id)
        .join(Instrument, StrategyDefinition.instrument_id == Instrument.id)
        .join(HistoricalDataset, BacktestRun.dataset_id == HistoricalDataset.id)
        .where(BacktestRun.status == "completed")
        .order_by(desc(BacktestRun.completed_at))
        .limit(200)
    )
    rows = result.all()
    version_ids = {s.current_version_id for _, s, _, _ in rows if s.current_version_id}
    versions: dict = {}
    if version_ids:
        vrows = await session.execute(select(StrategyVersion).where(StrategyVersion.id.in_(version_ids)))
        versions = {v.id: v for v in vrows.scalars().all()}
    entries: list[dict] = []
    for run, strategy, instrument, dataset in rows:
        version = versions.get(strategy.current_version_id) if strategy.current_version_id else None
        spec = dict(version.specification) if version and version.specification else None
        e = _entry(run, strategy, instrument, dataset, spec, profitable_only=profitable_only)
        if e:
            entries.append(e)
    entries.sort(key=lambda x: x["rank_score"], reverse=True)
    return entries[:limit]


def leaderboard_entries_sync(
    session: Session,
    *,
    limit: int = 15,
    profitable_only: bool = True,
) -> list[dict]:
    result = session.execute(
        select(BacktestRun, StrategyDefinition, Instrument, HistoricalDataset)
        .join(StrategyDefinition, BacktestRun.strategy_id == StrategyDefinition.id)
        .join(Instrument, StrategyDefinition.instrument_id == Instrument.id)
        .join(HistoricalDataset, BacktestRun.dataset_id == HistoricalDataset.id)
        .where(BacktestRun.status == "completed")
        .order_by(desc(BacktestRun.completed_at))
        .limit(200)
    )
    rows = result.all()
    version_ids = {s.current_version_id for _, s, _, _ in rows if s.current_version_id}
    versions: dict = {}
    if version_ids:
        vrows = session.execute(select(StrategyVersion).where(StrategyVersion.id.in_(version_ids)))
        versions = {v.id: v for v in vrows.scalars().all()}
    entries: list[dict] = []
    for run, strategy, instrument, dataset in rows:
        version = versions.get(strategy.current_version_id) if strategy.current_version_id else None
        spec = dict(version.specification) if version and version.specification else None
        e = _entry(run, strategy, instrument, dataset, spec, profitable_only=profitable_only)
        if e:
            entries.append(e)
    entries.sort(key=lambda x: x["rank_score"], reverse=True)
    return entries[:limit]