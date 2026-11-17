import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.backtest import BacktestRun
from app.models.instrument import Instrument
from app.models.strategy import StrategyDefinition, StrategyVersion
from app.models.user import User
from app.schemas.strategy import (
    StrategyCloneRequest,
    StrategyCreateRequest,
    StrategyDetail,
    StrategySummary,
    StrategyVersionOut,
)
from app.services.strategy_factory import clone_strategy_async, create_strategy_async

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategySummary])
async def list_strategies(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StrategySummary]:
    result = await db.execute(
        select(StrategyDefinition, Instrument.symbol)
        .join(Instrument, StrategyDefinition.instrument_id == Instrument.id)
        .order_by(StrategyDefinition.created_at.desc())
    )
    rows = result.all()
    return [
        StrategySummary(
            id=str(defn.id),
            name=defn.name,
            symbol=symbol,
            category=defn.category,
            timeframe=defn.timeframe,
            lifecycle=defn.lifecycle,
            created_at=defn.created_at.isoformat(),
        )
        for defn, symbol in rows
    ]


@router.post("", response_model=StrategyDetail)
async def create_strategy(
    body: StrategyCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyDetail:
    try:
        defn = await create_strategy_async(
            db,
            specification=body.specification,
            economic_rationale=body.economic_rationale or body.specification.get("name", ""),
            created_by=user.email,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await db.commit()
    return await get_strategy(str(defn.id), user, db)


@router.post("/{strategy_id}/clone", response_model=StrategyDetail)
async def clone_strategy(
    strategy_id: str,
    body: StrategyCloneRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyDetail:
    try:
        defn = await clone_strategy_async(
            db,
            strategy_id=uuid.UUID(strategy_id),
            new_name=body.name,
            created_by=user.email,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await db.commit()
    return await get_strategy(str(defn.id), user, db)


@router.get("/{strategy_id}", response_model=StrategyDetail)
async def get_strategy(
    strategy_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyDetail:
    result = await db.execute(
        select(StrategyDefinition, Instrument.symbol)
        .join(Instrument, StrategyDefinition.instrument_id == Instrument.id)
        .where(StrategyDefinition.id == uuid.UUID(strategy_id))
    )
    row = result.first()
    if not row:
        raise HTTPException(404, "Strategy not found")
    defn, symbol = row
    version_out = None
    if defn.current_version_id:
        ver = await db.get(StrategyVersion, defn.current_version_id)
        if ver:
            version_out = StrategyVersionOut(
                id=str(ver.id),
                version_number=ver.version_number,
                specification=ver.specification,
                changelog=ver.changelog,
                created_at=ver.created_at.isoformat(),
            )
    bt = await db.execute(
        select(BacktestRun)
        .where(BacktestRun.strategy_id == defn.id, BacktestRun.status == "completed")
        .order_by(BacktestRun.completed_at.desc())
        .limit(1)
    )
    latest = bt.scalar_one_or_none()
    latest_bt = None
    if latest:
        latest_bt = {
            "id": str(latest.id),
            "reproducibility_id": latest.reproducibility_id,
            "metrics": latest.metrics,
            "performance_category": (
                latest.performance_category.value
                if hasattr(latest.performance_category, "value")
                else str(latest.performance_category)
            ),
        }
    return StrategyDetail(
        id=str(defn.id),
        name=defn.name,
        symbol=symbol,
        category=defn.category,
        timeframe=defn.timeframe,
        lifecycle=defn.lifecycle,
        created_at=defn.created_at.isoformat(),
        current_version=version_out,
        latest_backtest=latest_bt,
    )