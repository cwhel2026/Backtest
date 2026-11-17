"""Forward-style simulation on the latest bars (not a broker account)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.backtest.bars import load_bars
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.models.backtest import BacktestRun
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.strategy import StrategyDefinition, StrategyVersion


def run_forward_simulation(
    session: Session,
    strategy: StrategyDefinition,
    backtest_run: BacktestRun,
    *,
    tail_bars: int = 100,
) -> dict:
    version = session.get(StrategyVersion, strategy.current_version_id)
    dataset = session.get(HistoricalDataset, backtest_run.dataset_id)
    instrument = session.get(Instrument, strategy.instrument_id)
    if not version or not dataset or not instrument:
        return {"summary": "Missing data for simulation", "error": True}

    bars = load_bars(session, dataset.id)
    if len(bars) < 20:
        return {"summary": "Not enough recent bars for live-style sim", "error": True}

    tail = bars[-tail_bars:]
    result = run_backtest(
        version.specification,
        tail,
        instrument,
        dataset.timeframe,
        BacktestAssumptions(slippage_ticks_per_side=1),
    )
    net = result.metrics.get("total_net_profit")
    trades = result.metrics.get("trade_count", 0)
    net_f = float(net) if net is not None else 0.0
    summary = f"Last {len(tail)} bars · {trades} simulated trades · net ${net_f:.2f} (research only)"
    return {
        "summary": summary,
        "tail_bars": len(tail),
        "metrics": result.metrics,
        "error": False,
    }