import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.backtest.bars import TIMEFRAME_MINUTES, load_bars
from app.db.session import SyncSessionLocal, get_db
from app.models.backtest import BacktestRun, BacktestTrade, OhlcvBar
from app.models.market_data import HistoricalDataset
from app.models.user import User
from app.schemas.backtest import (
    BacktestCreateRequest,
    BacktestRunSummary,
    BacktestTradeOut,
    DebuggerBarOut,
    SimulationLogOut,
)
from app.schemas.market_data import OhlcvBarOut
from app.services.market_data.ohlcv_parquet import has_store, read_bars as read_parquet_bars
from app.util.serde import enum_value, provisional_reproducibility_id
from app.worker.tasks import enqueue_backtest

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("", response_model=BacktestRunSummary)
async def create_backtest(
    body: BacktestCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BacktestRunSummary:
    from app.models.strategy import StrategyDefinition, StrategyVersion

    strategy = await db.get(StrategyDefinition, uuid.UUID(body.strategy_id))
    if not strategy:
        raise HTTPException(404, "Strategy not found")

    version_id = body.strategy_version_id or (
        str(strategy.current_version_id) if strategy.current_version_id else None
    )
    if not version_id:
        raise HTTPException(400, "Strategy has no version")
    version = await db.get(StrategyVersion, uuid.UUID(version_id))
    if not version:
        raise HTTPException(404, "Strategy version not found")

    run = BacktestRun(
        strategy_id=strategy.id,
        strategy_version_id=version.id,
        dataset_id=uuid.UUID(body.dataset_id),
        status="queued",
        engine_version="pending",
        reproducibility_id=provisional_reproducibility_id(),
        assumptions=body.assumptions,
        parameters=body.parameters,
    )
    db.add(run)
    await db.flush()
    try:
        enqueue_backtest(str(run.id), actor=user.email)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Backtest was saved but the worker queue is unavailable. Try again in a few seconds.",
        ) from exc
    return _serialize_run(run)


@router.get("", response_model=list[BacktestRunSummary])
async def list_backtests(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BacktestRunSummary]:
    result = await db.execute(select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(100))
    return [_serialize_run(r) for r in result.scalars()]


@router.get("/{run_id}", response_model=BacktestRunSummary)
async def get_backtest(
    run_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BacktestRunSummary:
    run = await db.get(BacktestRun, uuid.UUID(run_id))
    if not run:
        raise HTTPException(404, "Backtest not found")
    return _serialize_run(run)


@router.get("/{run_id}/trades", response_model=list[BacktestTradeOut])
async def get_backtest_trades(
    run_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BacktestTradeOut]:
    result = await db.execute(
        select(BacktestTrade)
        .where(BacktestTrade.backtest_run_id == uuid.UUID(run_id))
        .order_by(BacktestTrade.trade_number)
    )
    trades = result.scalars().all()
    return [
        BacktestTradeOut(
            id=str(t.id),
            trade_number=t.trade_number,
            direction=t.direction,
            quantity=t.quantity,
            signal_ts=t.signal_ts.isoformat(),
            entry_ts=t.entry_ts.isoformat(),
            entry_price=float(t.entry_price),
            exit_ts=t.exit_ts.isoformat(),
            exit_price=float(t.exit_price),
            stop_price=float(t.stop_price) if t.stop_price is not None else None,
            target_price=float(t.target_price) if t.target_price is not None else None,
            exit_reason=t.exit_reason,
            gross_pnl=float(t.gross_pnl),
            commissions=float(t.commissions),
            slippage=float(t.slippage),
            net_pnl=float(t.net_pnl),
            mae=float(t.mae) if t.mae is not None else None,
            mfe=float(t.mfe) if t.mfe is not None else None,
            meta=t.meta or {},
        )
        for t in trades
    ]


@router.get("/{run_id}/simulation-log", response_model=SimulationLogOut)
async def get_simulation_log(
    run_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SimulationLogOut:
    run = await db.get(BacktestRun, uuid.UUID(run_id))
    if not run:
        raise HTTPException(404, "Backtest not found")
    if not run.simulation_log:
        raise HTTPException(
            404,
            "This run has no simulation log. Re-run the backtest with engine 2.1+ to persist decision events.",
        )
    log = run.simulation_log
    return SimulationLogOut(
        decision_events=log.get("decision_events") or [],
        rejected_setups=log.get("rejected_setups") or [],
        simulation_provenance=log.get("simulation_provenance") or {},
        engine_version=log.get("engine_version"),
    )


@router.get("/{run_id}/debugger/bars", response_model=list[DebuggerBarOut])
async def debugger_bars(
    run_id: str,
    offset: int = 0,
    limit: int = 500,
    trade_number: int | None = None,
    padding: int = 120,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DebuggerBarOut]:
    """Windowed OHLCV bars for strategy debugger replay (no lookahead in client)."""
    run = await db.get(BacktestRun, uuid.UUID(run_id))
    if not run:
        raise HTTPException(404, "Backtest not found")
    provenance = (run.simulation_log or {}).get("simulation_provenance") or {}
    if provenance.get("dataset_checksum") and run.parameters:
        stored = run.parameters.get("dataset_checksum")
        if stored and provenance.get("dataset_checksum") not in (stored, None):
            raise HTTPException(409, "Dataset checksum mismatch — cannot replay with substituted data.")

    dataset = await db.get(HistoricalDataset, run.dataset_id)
    if not dataset:
        raise HTTPException(404, "Dataset not found")

    off = max(0, offset)
    lim = max(50, min(limit, 2000))
    pad = max(20, min(padding, 600))

    with SyncSessionLocal() as session:
        all_bars = load_bars(session, dataset.id)

    if trade_number is not None:
        result = await db.execute(
            select(BacktestTrade)
            .where(BacktestTrade.backtest_run_id == run.id)
            .where(BacktestTrade.trade_number == trade_number)
        )
        trade = result.scalar_one_or_none()
        if trade and all_bars:
            minutes = TIMEFRAME_MINUTES.get(dataset.timeframe, 5)
            # Find approximate bar index from signal timestamp
            sig = trade.signal_ts
            idx = next((i for i, b in enumerate(all_bars) if b.ts >= sig), 0)
            off = max(0, idx - pad)
            lim = min(len(all_bars) - off, pad * 2 + 200)

    slice_bars = all_bars[off : off + lim]
    return [
        DebuggerBarOut(
            bar_index=off + i,
            ts=b.ts.isoformat(),
            open=float(b.open),
            high=float(b.high),
            low=float(b.low),
            close=float(b.close),
            volume=int(b.volume),
        )
        for i, b in enumerate(slice_bars)
    ]


@router.get("/{run_id}/chart-bars", response_model=list[OhlcvBarOut])
async def backtest_chart_bars(
    run_id: str,
    trade_number: int,
    padding: int = 80,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OhlcvBarOut]:
    run = await db.get(BacktestRun, uuid.UUID(run_id))
    if not run:
        raise HTTPException(404, "Backtest not found")
    result = await db.execute(
        select(BacktestTrade)
        .where(BacktestTrade.backtest_run_id == run.id)
        .where(BacktestTrade.trade_number == trade_number)
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")
    dataset = await db.get(HistoricalDataset, run.dataset_id)
    if not dataset:
        raise HTTPException(404, "Dataset not found")
    pad = max(10, min(padding, 400))
    minutes = TIMEFRAME_MINUTES.get(dataset.timeframe, 5)
    window = timedelta(minutes=minutes * pad)
    start = trade.signal_ts - window
    end = trade.exit_ts + window

    if has_store(run.dataset_id):
        stored = read_parquet_bars(run.dataset_id, start=start, end=end)
        return [
            OhlcvBarOut(
                ts=ts.isoformat(),
                open=float(o),
                high=float(h),
                low=float(low),
                close=float(c),
                volume=int(v),
            )
            for ts, o, h, low, c, v in stored
        ]

    result = await db.execute(
        select(OhlcvBar)
        .where(OhlcvBar.dataset_id == run.dataset_id)
        .where(OhlcvBar.ts >= start)
        .where(OhlcvBar.ts <= end)
        .order_by(OhlcvBar.ts)
    )
    rows = result.scalars().all()
    if rows:
        return [
            OhlcvBarOut(
                ts=r.ts.isoformat(),
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=int(r.volume),
            )
            for r in rows
        ]

    with SyncSessionLocal() as session:
        bars = load_bars(session, run.dataset_id, start=start, end=end)
    return [
        OhlcvBarOut(
            ts=b.ts.isoformat(),
            open=float(b.open),
            high=float(b.high),
            low=float(b.low),
            close=float(b.close),
            volume=b.volume,
        )
        for b in bars
    ]


def _serialize_run(run: BacktestRun) -> BacktestRunSummary:
    return BacktestRunSummary(
        id=str(run.id),
        strategy_id=str(run.strategy_id),
        dataset_id=str(run.dataset_id),
        status=run.status,
        performance_category=enum_value(run.performance_category),
        reproducibility_id=run.reproducibility_id,
        engine_version=run.engine_version,
        metrics=run.metrics,
        assumptions=run.assumptions,
        warnings=run.warnings,
        equity_curve=run.equity_curve,
        error=run.error,
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        has_simulation_log=bool(run.simulation_log),
    )