"""Autonomous prop-firm research loop — data → ideas → backtest → live-style sim."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.backtest import BacktestRun
from app.models.enums import ResearchJobKind, ResearchJobStatus
from app.models.market_data import HistoricalDataset
from app.models.instrument import Instrument
from app.models.research import ResearchActivity, ResearchJob
from app.models.strategy import StrategyDefinition
from app.services.ai_research import generate_hypothesis_and_spec
from app.services.backtest_runner import execute_backtest_run
from app.services.market_data.ingestion_runner import run_yahoo_ingestion
from app.services.forward_sim import run_forward_simulation
from app.services.strategy_factory import create_strategy_sync

PROP_SYMBOLS = ("MES", "MNQ")
PROMPTS = (
    "Opening range breakout for prop firm risk rules",
    "EMA momentum trend with tight stop",
    "VWAP mean reversion during RTH",
)


def _ingest_yahoo(session: Session, symbol: str, actor: str) -> HistoricalDataset:
    end = datetime.now(UTC)
    start = end - timedelta(days=7)
    payload = {
        "provider": "yahoo",
        "instrument_symbol": symbol,
        "timeframe": "5m",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    return run_yahoo_ingestion(session, payload)


def _latest_dataset(session: Session, symbol: str) -> HistoricalDataset | None:
    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if not inst:
        return None
    return session.execute(
        select(HistoricalDataset)
        .where(HistoricalDataset.instrument_id == inst.id, HistoricalDataset.timeframe == "5m")
        .order_by(desc(HistoricalDataset.downloaded_at))
        .limit(1)
    ).scalar_one_or_none()


def run_autonomous_prop_cycle(session: Session, actor: str = "autopilot") -> dict:
    """One full cycle: refresh Yahoo data, generate strategies, backtest, forward sim."""
    settings = get_settings()
    summary: dict = {"symbols": {}, "strategies": [], "backtests": [], "sims": []}

    job = ResearchJob(
        kind=ResearchJobKind.VALIDATION,
        status=ResearchJobStatus.RUNNING,
        title="Autonomous prop research cycle",
        message="Updating market data",
        started_at=datetime.now(UTC),
        payload={"actor": actor},
    )
    session.add(job)
    session.flush()

    try:
        datasets: dict[str, HistoricalDataset] = {}
        for symbol in PROP_SYMBOLS:
            try:
                ds = _ingest_yahoo(session, symbol, actor)
                session.commit()
                datasets[symbol] = ds
                summary["symbols"][symbol] = {"dataset_id": str(ds.id), "rows": ds.row_count}
            except Exception as exc:
                session.rollback()
                ds = _latest_dataset(session, symbol)
                if ds:
                    datasets[symbol] = ds
                    summary["symbols"][symbol] = {
                        "dataset_id": str(ds.id),
                        "rows": ds.row_count,
                        "warning": str(exc),
                    }

        job.message = "Generating and testing strategies"
        session.commit()

        for idx, symbol in enumerate(PROP_SYMBOLS):
            ds = datasets.get(symbol)
            if not ds:
                continue
            prompt = PROMPTS[idx % len(PROMPTS)]
            rationale, spec = generate_hypothesis_and_spec(symbol, "5m", prompt)
            strategy = create_strategy_sync(
                session,
                specification=spec,
                economic_rationale=rationale,
                created_by="autopilot",
            )
            session.flush()
            summary["strategies"].append({"id": str(strategy.id), "name": strategy.name})

            run = BacktestRun(
                strategy_id=strategy.id,
                strategy_version_id=strategy.current_version_id,
                dataset_id=ds.id,
                status="queued",
                engine_version="pending",
                reproducibility_id="pending",
                assumptions={"slippage_ticks_per_side": 1},
                parameters={},
            )
            session.add(run)
            session.flush()
            execute_backtest_run(session, run.id)
            session.commit()
            summary["backtests"].append(
                {
                    "id": str(run.id),
                    "strategy_id": str(strategy.id),
                    "metrics": run.metrics,
                    "status": run.status,
                }
            )

            if run.status == "completed" and settings.autonomous_forward_sim:
                sim = run_forward_simulation(session, strategy, run, tail_bars=120)
                summary["sims"].append(sim)
                session.add(
                    ResearchActivity(
                        headline=f"Live sim (no broker): {strategy.name}",
                        detail=sim.get("summary", ""),
                        meta={"strategy_id": str(strategy.id), "run_id": str(run.id), "sim": sim},
                    )
                )

        job.status = ResearchJobStatus.COMPLETED
        job.progress_pct = 100
        job.message = "Cycle complete"
        job.completed_at = datetime.now(UTC)
        job.payload = {**job.payload, "summary": summary}
        session.add(
            ResearchActivity(
                headline="Autonomous cycle finished",
                detail=f"Tested {len(summary['backtests'])} strategies on MES/MNQ",
                job_id=job.id,
                meta=summary,
            )
        )
        session.commit()
        return summary
    except Exception as exc:
        session.rollback()
        job = session.get(ResearchJob, job.id)
        if job:
            job.status = ResearchJobStatus.FAILED
            job.error = str(exc)
            job.message = str(exc)
            job.completed_at = datetime.now(UTC)
            session.add(
                ResearchActivity(
                    headline="Autonomous cycle failed",
                    detail=str(exc),
                    job_id=job.id,
                )
            )
            session.commit()
        raise