"""Ranked backtest leaderboard with strategy context."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.backtest import BacktestRun
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.strategy import StrategyDefinition
from app.services.prop_screen import (
    format_metric_display,
    is_profitable_backtest,
    prop_gate_miss,
    prop_readiness_score,
    rank_score,
)


def _entry(
    run: BacktestRun,
    strategy: StrategyDefinition,
    symbol: str,
    dataset_tf: str,
    *,
    profitable_only: bool,
) -> dict | None:
    metrics = run.metrics or {}
    tf = dataset_tf or strategy.timeframe
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
        "symbol": symbol,
        "category": strategy.category,
        "timeframe": tf,
        "entry_type": (metrics.get("entry_type") if isinstance(metrics.get("entry_type"), str) else None)
        or _entry_type_from_strategy(strategy),
        "origin": origin,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "prop_ready_score": prop_readiness_score(metrics, timeframe=tf),
        "passes_prop_screen": passes,
        "gate_miss": None if passes else prop_gate_miss(metrics, reverse=reverse, timeframe=tf),
        "metrics": display,
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
        select(BacktestRun, StrategyDefinition, Instrument.symbol, HistoricalDataset.timeframe)
        .join(StrategyDefinition, BacktestRun.strategy_id == StrategyDefinition.id)
        .join(Instrument, StrategyDefinition.instrument_id == Instrument.id)
        .join(HistoricalDataset, BacktestRun.dataset_id == HistoricalDataset.id)
        .where(BacktestRun.status == "completed")
        .order_by(desc(BacktestRun.completed_at))
        .limit(200)
    )
    rows = result.all()
    entries: list[dict] = []
    for run, strategy, symbol, tf in rows:
        e = _entry(run, strategy, symbol, tf, profitable_only=profitable_only)
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
        select(BacktestRun, StrategyDefinition, Instrument.symbol, HistoricalDataset.timeframe)
        .join(StrategyDefinition, BacktestRun.strategy_id == StrategyDefinition.id)
        .join(Instrument, StrategyDefinition.instrument_id == Instrument.id)
        .join(HistoricalDataset, BacktestRun.dataset_id == HistoricalDataset.id)
        .where(BacktestRun.status == "completed")
        .order_by(desc(BacktestRun.completed_at))
        .limit(200)
    )
    entries: list[dict] = []
    for run, strategy, symbol, tf in result.all():
        e = _entry(run, strategy, symbol, tf, profitable_only=profitable_only)
        if e:
            entries.append(e)
    entries.sort(key=lambda x: x["rank_score"], reverse=True)
    return entries[:limit]