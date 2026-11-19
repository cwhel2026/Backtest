from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.instrument import Instrument
from app.models.user import User
from app.schemas.instrument import InstrumentOut
from app.services.instruments import PRIMARY_RESEARCH_SYMBOLS

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut])
async def list_instruments(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    scope: str = Query("primary", pattern="^(primary|all)$"),
) -> list[InstrumentOut]:
    q = select(Instrument).where(Instrument.is_active).order_by(Instrument.symbol)
    if scope == "primary":
        q = q.where(Instrument.symbol.in_(PRIMARY_RESEARCH_SYMBOLS))
    result = await db.execute(q)
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
            primary_research=i.symbol in PRIMARY_RESEARCH_SYMBOLS
            or bool((i.metadata_extra or {}).get("primary_research")),
        )
        for i in items
    ]