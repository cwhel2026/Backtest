import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.backtest import OhlcvBar
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.user import User
from app.schemas.market_data import HistoricalDatasetOut, OhlcvBarOut, ProviderHealthOut
from app.services.market_data.csv_import import import_csv_bars
from app.services.market_data.ohlcv_parquet import has_store, read_bars as read_parquet_bars
from app.services.market_data.providers import PROVIDER_REGISTRY, all_provider_health
from app.worker.tasks import create_ingestion_job, run_data_ingestion

settings = get_settings()
_sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(bind=_sync_engine, autoflush=False, autocommit=False)

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
            meta=d.meta,
        )
        for d in rows
    ]


@router.post("/import-csv", response_model=HistoricalDatasetOut)
async def import_csv_dataset(
    instrument_symbol: str = Form(...),
    timeframe: str = Form("5m"),
    label: str = Form("user_import"),
    provider_slug: str = Form("databento"),
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HistoricalDatasetOut:
    content = (await file.read()).decode("utf-8")
    inst = (
        await db.execute(select(Instrument).where(Instrument.symbol == instrument_symbol))
    ).scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    def _import() -> HistoricalDataset:
        with SyncSession() as session:
            ds = import_csv_bars(
                session,
                provider_slug=provider_slug,
                instrument_id=inst.id,
                timeframe=timeframe,
                label=label,
                csv_text=content,
            )
            session.commit()
            session.refresh(ds)
            return ds

    dataset = _import()
    return HistoricalDatasetOut(
        id=str(dataset.id),
        instrument_id=str(dataset.instrument_id),
        provider_id=str(dataset.provider_id),
        timeframe=dataset.timeframe,
        row_count=dataset.row_count,
        validation_status=dataset.validation_status.value,
        coverage_start=dataset.coverage_start.isoformat() if dataset.coverage_start else None,
        coverage_end=dataset.coverage_end.isoformat() if dataset.coverage_end else None,
        version_tag=dataset.version_tag,
        meta=dataset.meta,
    )


@router.get("/datasets/{dataset_id}/bars", response_model=list[OhlcvBarOut])
async def dataset_bars(
    dataset_id: str,
    limit: int = 500,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OhlcvBarOut]:
    cap = min(limit, 2000)
    ds_id = uuid.UUID(dataset_id)
    if has_store(ds_id):
        stored = read_parquet_bars(ds_id)[:cap]
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
        .where(OhlcvBar.dataset_id == ds_id)
        .order_by(OhlcvBar.ts)
        .limit(cap)
    )
    rows = result.scalars().all()
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


@router.post("/ingest")
async def request_ingestion(
    body: IngestionRequest,
    background_tasks: BackgroundTasks,
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
    job_id = create_ingestion_job(meta, actor=user.email)
    try:
        run_data_ingestion.delay(job_id)
        status = "queued"
    except Exception:
        background_tasks.add_task(run_data_ingestion, job_id)
        status = "processing"
    return {"job_id": job_id, "status": status, "meta": meta}