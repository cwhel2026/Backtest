import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.backtest import BacktestRun, BacktestTrade
from app.models.user import User
from app.schemas.backtest import BacktestCreateRequest, BacktestRunSummary, BacktestTradeOut
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
        reproducibility_id="pending",
        assumptions=body.assumptions,
        parameters=body.parameters,
    )
    db.add(run)
    await db.flush()
    await db.commit()
    enqueue_backtest(str(run.id), actor=user.email)
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
            exit_reason=t.exit_reason,
            gross_pnl=float(t.gross_pnl),
            commissions=float(t.commissions),
            slippage=float(t.slippage),
            net_pnl=float(t.net_pnl),
            mae=float(t.mae) if t.mae is not None else None,
            mfe=float(t.mfe) if t.mfe is not None else None,
        )
        for t in trades
    ]


def _serialize_run(run: BacktestRun) -> BacktestRunSummary:
    return BacktestRunSummary(
        id=str(run.id),
        strategy_id=str(run.strategy_id),
        dataset_id=str(run.dataset_id),
        status=run.status,
        performance_category=run.performance_category.value,
        reproducibility_id=run.reproducibility_id,
        engine_version=run.engine_version,
        metrics=run.metrics,
        assumptions=run.assumptions,
        warnings=run.warnings,
        equity_curve=run.equity_curve,
        error=run.error,
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )