from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.market_data import HistoricalDataset
from app.models.user import User
from app.schemas.market_data import HistoricalDatasetOut, ProviderHealthOut
from app.services.market_data.providers import PROVIDER_REGISTRY, all_provider_health
from app.worker.tasks import enqueue_data_ingestion

router = APIRouter(prefix="/market-data", tags=["market-data"])


class IngestionRequest(BaseModel):
    provider_slug: str
    instrument_symbol: str
    timeframe: str = "1m"
    start: datetime
    end: datetime


@router.get("/providers", response_model=list[ProviderHealthOut])
async def list_providers(_: User = Depends(get_current_user)) -> list[ProviderHealthOut]:
    health = await all_provider_health()
    return [
        ProviderHealthOut(
            slug=h.slug,
            display_name=h.display_name,
            state=h.state.value,
            message=h.message,
            capabilities=h.capabilities,
        )
        for h in health
    ]


@router.get("/datasets", response_model=list[HistoricalDatasetOut])
async def list_datasets(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[HistoricalDatasetOut]:
    result = await db.execute(select(HistoricalDataset).order_by(HistoricalDataset.downloaded_at.desc()))
    rows = result.scalars().all()
    return [
        HistoricalDatasetOut(
            id=str(d.id),
            instrument_id=str(d.instrument_id),
            provider_id=str(d.provider_id),
            timeframe=d.timeframe,
            row_count=d.row_count,
            validation_status=d.validation_status.value,
            coverage_start=d.coverage_start.isoformat() if d.coverage_start else None,
            coverage_end=d.coverage_end.isoformat() if d.coverage_end else None,
            version_tag=d.version_tag,
        )
        for d in rows
    ]


@router.post("/ingest")
async def request_ingestion(
    body: IngestionRequest,
    user: User = Depends(get_current_user),
) -> dict:
    provider = PROVIDER_REGISTRY.get(body.provider_slug)
    if not provider:
        raise HTTPException(status_code=404, detail="Unknown provider")
    try:
        meta = await provider.ingest_historical(
            body.instrument_symbol, body.timeframe, body.start, body.end
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    job_id = enqueue_data_ingestion(meta, actor=user.email)
    return {"job_id": job_id, "status": "queued", "meta": meta}