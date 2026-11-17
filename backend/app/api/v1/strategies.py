from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.instrument import Instrument
from app.models.strategy import StrategyDefinition
from app.models.user import User
from app.schemas.strategy import StrategySummary

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