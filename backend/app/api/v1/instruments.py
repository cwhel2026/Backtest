from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.instrument import Instrument
from app.models.user import User
from app.schemas.instrument import InstrumentOut

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut])
async def list_instruments(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InstrumentOut]:
    result = await db.execute(select(Instrument).where(Instrument.is_active).order_by(Instrument.symbol))
    items = result.scalars().all()
    return [
        InstrumentOut(
            id=str(i.id),
            symbol=i.symbol,
            name=i.name,
            asset_class=i.asset_class,
            exchange=i.exchange,
            tick_size=i.tick_size,
            tick_value=i.tick_value,
            multiplier=i.multiplier,
            is_micro=i.is_micro,
            micro_of=i.micro_of,
        )
        for i in items
    ]