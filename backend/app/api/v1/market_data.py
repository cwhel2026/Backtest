import uuid
from datetime import datetime
from decimal import Decimal

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
from app.schemas.market_data import (
    DatasetReadinessOut,
    HistoricalDatasetOut,
    IngestEstimateRequest,
    OhlcvBarOut,
    ProviderHealthOut,
)
from app.services.market_data.budget import budget_status, reserve_approval
from app.services.market_data.csv_import import import_csv_bars
from app.backtest.bars import Bar
from app.services.market_data.databento_client import quote_download_cost
from app.services.market_data.dataset_catalog import find_validated_duplicate, ingest_fingerprint
from app.services.market_data.ohlcv_parquet import has_store, read_bars as read_parquet_bars
from app.services.market_data.provider_audit import PROVIDER_TIERS
from app.services.market_data.providers import PROVIDER_REGISTRY, all_provider_health
from app.services.market_data.quality import audit_bars, estimate_download_cost_usd
from app.services.market_data.validate_dataset import validate_and_persist
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
    confirm_paid: bool = False
    budget_override: bool = False
    force_refresh: bool = False
    approved_cost_usd: float | None = None


class IngestCostEstimate(BaseModel):
    provider_slug: str
    instrument_symbol: str
    timeframe: str = "5m"
    days: int = 30


def _dataset_out(d: HistoricalDataset) -> HistoricalDatasetOut:
    meta = d.meta or {}
    return HistoricalDatasetOut(
        id=str(d.id),
        instrument_id=str(d.instrument_id),
        provider_id=str(d.provider_id),
        timeframe=d.timeframe,
        row_count=d.row_count,
        validation_status=d.validation_status.value,
        coverage_start=d.coverage_start.isoformat() if d.coverage_start else None,
        coverage_end=d.coverage_end.isoformat() if d.coverage_end else None,
        version_tag=d.version_tag,
        content_checksum=d.content_checksum,
        storage_uri=d.storage_uri or meta.get("storage_uri"),
        quality_class=meta.get("quality_class"),
        meta=meta,
    )


@router.get("/budget")
async def research_data_budget(
    _: User = Depends(get_current_user),
) -> dict:
    with SyncSession() as session:
        return budget_status(session)


@router.get("/provider-tiers")
async def provider_tiers(_: User = Depends(get_current_user)) -> dict:
    return PROVIDER_TIERS


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
    return [_dataset_out(d) for d in rows]


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
            validate_and_persist(session, ds, symbol=instrument_symbol, tick_size=inst.tick_size)
            session.commit()
            session.refresh(ds)
            return ds

    dataset = _import()
    return _dataset_out(dataset)


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


@router.post("/ingest/estimate", response_model=dict)
async def ingest_cost_estimate(
    body: IngestCostEstimate,
    _: User = Depends(get_current_user),
) -> dict:
    return estimate_download_cost_usd(
        body.provider_slug,
        symbols=1,
        days=body.days,
        timeframe=body.timeframe,
    )


@router.post("/ingest/estimate-range", response_model=dict)
async def ingest_cost_estimate_range(
    body: IngestEstimateRequest,
    _: User = Depends(get_current_user),
) -> dict:
    start = datetime.fromisoformat(body.start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(body.end.replace("Z", "+00:00"))
    if body.provider_slug == "databento":
        try:
            return quote_download_cost(body.instrument_symbol, start, end).to_dict()
        except ValueError as exc:
            days = max(1, int((end - start).total_seconds() // 86400))
            fallback = estimate_download_cost_usd("databento", symbols=1, days=days, timeframe=body.timeframe)
            fallback["error"] = str(exc)
            return fallback
    days = max(1, int((end - start).total_seconds() // 86400))
    return estimate_download_cost_usd(body.provider_slug, symbols=1, days=days, timeframe=body.timeframe)


@router.get("/datasets/{dataset_id}/quality")
async def dataset_quality(
    dataset_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cap = 50_000
    ds_id = uuid.UUID(dataset_id)
    ds = (
        await db.execute(select(HistoricalDataset).where(HistoricalDataset.id == ds_id))
    ).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    bars: list[Bar] = []
    if has_store(ds_id):
        for ts, o, h, low, c, v in read_parquet_bars(ds_id)[:cap]:
            bars.append(
                Bar(
                    ts=ts,
                    open=Decimal(str(o)),
                    high=Decimal(str(h)),
                    low=Decimal(str(low)),
                    close=Decimal(str(c)),
                    volume=int(v),
                )
            )
    else:
        rows = (
            await db.execute(
                select(OhlcvBar).where(OhlcvBar.dataset_id == ds_id).order_by(OhlcvBar.ts).limit(cap)
            )
        ).scalars().all()
        for r in rows:
            bars.append(
                Bar(ts=r.ts, open=r.open, high=r.high, low=r.low, close=r.close, volume=int(r.volume or 0))
            )
    source = (ds.meta or {}).get("provider") if isinstance(ds.meta, dict) else None
    return audit_bars(bars, timeframe=ds.timeframe, source=source).to_dict()


@router.get("/datasets/{dataset_id}/readiness", response_model=DatasetReadinessOut)
async def dataset_readiness(
    dataset_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetReadinessOut:
    ds = await db.get(HistoricalDataset, uuid.UUID(dataset_id))
    if not ds:
        raise HTTPException(404, "Dataset not found")
    meta = ds.meta or {}
    qclass = (meta.get("quality_class") or "unknown").lower()
    return DatasetReadinessOut(
        dataset_id=str(ds.id),
        quality_class=qclass,
        validation_status=ds.validation_status.value,
        video_readiness=meta.get("video_readiness") or {},
        backtest_allowed=qclass in ("ready", "warning"),
    )


@router.post("/ingest")
async def request_ingestion(
    body: IngestionRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    provider = PROVIDER_REGISTRY.get(body.provider_slug)
    if not provider:
        raise HTTPException(status_code=404, detail="Unknown provider")
    days = max(1, int((body.end - body.start).total_seconds() // 86400))
    if body.provider_slug == "databento" and settings.databento_configured:
        try:
            cost = quote_download_cost(body.instrument_symbol, body.start, body.end).to_dict()
        except ValueError as exc:
            cost = estimate_download_cost_usd("databento", symbols=1, days=days, timeframe=body.timeframe)
            cost["error"] = str(exc)
    else:
        cost = estimate_download_cost_usd(body.provider_slug, symbols=1, days=days, timeframe=body.timeframe)

    estimated_usd = float(cost.get("estimated_usd") or 0)
    if cost.get("requires_approval") and not body.confirm_paid:
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Paid provider requires confirm_paid=true after reviewing the cost estimate.",
                "estimate": cost,
            },
        )

    inst = (
        await db.execute(select(Instrument).where(Instrument.symbol == body.instrument_symbol))
    ).scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    fingerprint = ingest_fingerprint(
        provider_slug=body.provider_slug,
        instrument_symbol=body.instrument_symbol,
        timeframe=body.timeframe,
        start=body.start,
        end=body.end,
    )
    if not body.force_refresh:
        with SyncSession() as session:
            cached = find_validated_duplicate(
                session,
                fingerprint=fingerprint,
                instrument_id=inst.id,
                timeframe=body.timeframe,
            )
            if cached:
                return {
                    "status": "cached",
                    "dataset_id": str(cached.id),
                    "message": "Equivalent validated data already in library — no duplicate paid download.",
                    "meta": {"ingest_fingerprint": fingerprint},
                }

    if cost.get("requires_approval") and estimated_usd > 0:
        with SyncSession() as session:
            try:
                reserve_approval(session, estimated_usd, allow_over_budget=body.budget_override)
                session.commit()
            except ValueError as exc:
                raise HTTPException(status_code=402, detail=str(exc)) from exc

    try:
        meta = await provider.ingest_historical(
            body.instrument_symbol, body.timeframe, body.start, body.end
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    meta = {
        **meta,
        "ingest_fingerprint": fingerprint,
        "approved_cost_usd": body.approved_cost_usd or estimated_usd,
        "cost_estimate_source": cost.get("source", "heuristic"),
    }
    job_id = create_ingestion_job(meta, actor=user.email)
    try:
        run_data_ingestion.delay(job_id)
        status = "queued"
    except Exception:
        background_tasks.add_task(run_data_ingestion, job_id)
        status = "processing"
    return {"job_id": job_id, "status": status, "meta": meta}


@router.get("/health")
async def market_data_health(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.core.config import get_settings
    from app.models.instrument import Instrument
    from app.services.market_data.databento_client import check_dataset_range
    from app.services.market_data.ohlcv_s3 import check_s3_reachable
    from app.services.market_data.storage_backend import ensure_ohlcv_storage
    from app.services.market_data.storage_health import (
        check_database,
        check_not_ephemeral,
        check_store_writable,
        store_paths,
    )

    storage_boot = ensure_ohlcv_storage()

    settings = get_settings()

    db_ok = True
    db_msg = "async pool ok"
    try:
        await db.execute(select(Instrument).limit(1))
    except Exception as exc:
        db_ok = False
        db_msg = str(exc)

    sync_db_ok, sync_db_msg = True, "n/a"
    with SyncSession() as session:
        sync_db_ok, sync_db_msg = check_database(session)
        budget = budget_status(session)

    store_ok, store_msg = check_store_writable()
    persist_ok, persist_msg = check_not_ephemeral()
    s3_ok, s3_msg = check_s3_reachable()

    databento = {
        "configured": settings.databento_configured,
        "live_smoke_enabled": settings.databento_live_smoke,
    }
    if settings.databento_configured:
        databento["range_probe"] = check_dataset_range(
            datetime.fromisoformat("2024-06-01T00:00:00+00:00"),
            datetime.fromisoformat("2024-06-02T00:00:00+00:00"),
        )

    datasets = (await db.execute(select(HistoricalDataset).order_by(HistoricalDataset.downloaded_at.desc()).limit(20))).scalars().all()
    ready = sum(1 for d in datasets if (d.meta or {}).get("quality_class") == "ready")
    blocked = sum(1 for d in datasets if (d.meta or {}).get("quality_class") == "blocked")

    return {
        "database": {"async_ok": db_ok, "async_detail": db_msg, "sync_ok": sync_db_ok, "sync_detail": sync_db_msg},
        "storage": {
            **store_paths(),
            "writable": store_ok,
            "writable_detail": store_msg,
            "persistent_ok": persist_ok,
            "persistent_detail": persist_msg,
            "s3_ok": s3_ok,
            "s3_detail": s3_msg,
            "boot": storage_boot,
        },
        "databento": databento,
        "budget": budget,
        "datasets": {
            "count_recent": len(datasets),
            "ready": ready,
            "blocked": blocked,
        },
        "providers": [p.slug for p in await all_provider_health()],
    }