import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.backtest import ENGINE_VERSION
from app.util.serde import clamp_str
from app.backtest.bars import load_bars
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.backtest.reproducibility import build_reproducibility_id
from app.models.backtest import BacktestRun, BacktestTrade
from app.models.enums import PerformanceCategory, StrategyLifecycle
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.strategy import StrategyDefinition, StrategyVersion


def execute_backtest_run(session: Session, run_id: uuid.UUID) -> None:
    run = session.get(BacktestRun, run_id)
    if not run:
        return
    run.status = "running"
    run.started_at = datetime.now(UTC)
    session.commit()

    try:
        version = session.get(StrategyVersion, run.strategy_version_id)
        strategy = session.get(StrategyDefinition, run.strategy_id)
        dataset = session.get(HistoricalDataset, run.dataset_id)
        instrument = session.get(Instrument, strategy.instrument_id) if strategy else None
        if not all([version, strategy, dataset, instrument]):
            raise ValueError("Missing strategy, version, dataset, or instrument")

        meta = dataset.meta or {}
        qclass = (meta.get("quality_class") or "").lower()
        if qclass == "blocked" or dataset.validation_status.value == "failed":
            raise ValueError(
                "Dataset quality is BLOCKED — fix or ingest validated data before backtesting."
            )
        run_assumptions = run.assumptions or {}
        require_genuine = run_assumptions.get("require_genuine_historical", True)
        if require_genuine is not False:
            from app.services.market_data.data_lineage import assert_genuine_for_backtest

            if not meta.get("data_lineage"):
                raise ValueError(
                    "Dataset missing data_lineage metadata — ingest via Databento or CSV import "
                    "and wait for validation to complete before genuine research backtests."
                )
            assert_genuine_for_backtest(meta)

        bars = load_bars(session, dataset.id)
        if not bars:
            raise ValueError("Dataset has no OHLCV bars — import CSV or connect a data provider.")

        bt_assume = BacktestAssumptions(
            slippage_ticks_per_side=int(run_assumptions.get("slippage_ticks_per_side", 1)),
            commission_per_side=Decimal(str(run_assumptions["commission_per_side"]))
            if run_assumptions.get("commission_per_side") is not None
            else None,
        )

        spec = dict(version.specification)
        entry_type = (spec.get("entry") or {}).get("type")
        if entry_type in ("video_liquidity_sweep", "video_anchor_bos", "berg_tnb_model_v1"):
            spec["data_context"] = {
                **(spec.get("data_context") or {}),
                "rollover_events": meta.get("rollover_events") or [],
                "dataset_version": dataset.version_tag,
                "dataset_checksum": dataset.content_checksum,
            }

        result = run_backtest(
            spec,
            bars,
            instrument,
            dataset.timeframe,
            bt_assume,
        )

        run.reproducibility_id = build_reproducibility_id(
            strategy_version_id=str(version.id),
            dataset_id=str(dataset.id),
            dataset_version=dataset.version_tag,
            bar_count=len(bars),
            assumptions=run.assumptions,
            parameters=run.parameters,
        )
        run.metrics = result.metrics
        run.equity_curve = result.equity_curve
        run.warnings = result.warnings
        run.engine_version = ENGINE_VERSION
        run.parameters = {
            **(run.parameters or {}),
            "dataset_version_tag": dataset.version_tag,
            "dataset_checksum": dataset.content_checksum,
            "dataset_quality_class": meta.get("quality_class"),
            "dataset_provider_id": str(dataset.provider_id),
            "instrument_symbol": instrument.symbol,
            "timeframe": dataset.timeframe,
            "coverage_start": dataset.coverage_start.isoformat() if dataset.coverage_start else None,
            "coverage_end": dataset.coverage_end.isoformat() if dataset.coverage_end else None,
        }
        run.performance_category = PerformanceCategory.BACKTEST
        run.completed_at = datetime.now(UTC)
        run.status = "completed"
        if result.decision_events is not None or result.rejected_setups is not None:
            run.simulation_log = {
                "decision_events": result.decision_events or [],
                "rejected_setups": result.rejected_setups or [],
                "simulation_provenance": result.simulation_provenance or {},
                "engine_version": ENGINE_VERSION,
            }

        session.execute(delete(BacktestTrade).where(BacktestTrade.backtest_run_id == run.id))
        for t in result.trades:
            session.add(
                BacktestTrade(
                    backtest_run_id=run.id,
                    trade_number=t["trade_number"],
                    direction=t["direction"],
                    quantity=t["quantity"],
                    signal_ts=t["signal_ts"],
                    entry_ts=t["entry_ts"],
                    entry_price=t["entry_price"],
                    exit_ts=t["exit_ts"],
                    exit_price=t["exit_price"],
                    stop_price=t.get("stop_price"),
                    target_price=t.get("target_price"),
                    exit_reason=clamp_str(str(t["exit_reason"]), 64),
                    gross_pnl=t["gross_pnl"],
                    commissions=t["commissions"],
                    slippage=t["slippage"],
                    net_pnl=t["net_pnl"],
                    mae=t.get("mae"),
                    mfe=t.get("mfe"),
                    meta=t.get("meta", {}),
                )
            )

        strategy.lifecycle = StrategyLifecycle.BACKTESTING
        session.commit()
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        run.completed_at = datetime.now(UTC)
        session.commit()
        raise