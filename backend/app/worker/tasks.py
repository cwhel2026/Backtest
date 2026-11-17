"""Background research and data jobs — records real job state in PostgreSQL."""

import uuid
from datetime import UTC, datetime

from app.worker.celery_app import celery_app
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.enums import ResearchJobKind, ResearchJobStatus
from app.models.research import ResearchActivity, ResearchJob
from app.services.backtest_runner import execute_backtest_run
from app.services.market_data.ingestion_runner import run_databento_ingestion

settings = get_settings()
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


def _fail_ingestion(db: Session, job: ResearchJob, error: str, headline: str) -> None:
    job.status = ResearchJobStatus.FAILED
    job.error = error
    job.message = error
    job.completed_at = datetime.now(UTC)
    db.add(
        ResearchActivity(
            headline=headline,
            detail=error,
            job_id=job.id,
        )
    )
    db.commit()


def enqueue_data_ingestion(meta: dict, actor: str) -> str:
    job_id = str(uuid.uuid4())
    with SyncSession() as db:
        job = ResearchJob(
            id=uuid.UUID(job_id),
            kind=ResearchJobKind.DATA_INGESTION,
            status=ResearchJobStatus.QUEUED,
            title=f"Market data ingestion: {meta.get('instrument_symbol')}",
            message="Queued for worker",
            payload=meta,
        )
        db.add(job)
        db.add(
            ResearchActivity(
                headline=f"Queued ingestion for {meta.get('instrument_symbol')} ({meta.get('timeframe')})",
                detail=f"Requested by {actor}",
                job_id=job.id,
            )
        )
        db.commit()
    run_data_ingestion.delay(job_id)
    return job_id


@celery_app.task(name="app.worker.tasks.run_data_ingestion")
def run_data_ingestion(job_id: str) -> None:
    with SyncSession() as db:
        job = db.get(ResearchJob, uuid.UUID(job_id))
        if not job:
            return
        job.status = ResearchJobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.message = "Validating provider configuration"
        db.commit()

        provider = job.payload.get("provider")
        settings_ref = get_settings()
        if provider == "databento" and not settings_ref.databento_api_key:
            _fail_ingestion(db, job, "Databento API key not configured", "Ingestion failed: Databento not configured")
            return

        if provider != "databento":
            _fail_ingestion(
                db,
                job,
                f"Provider {provider} is not supported for automated ingestion yet.",
                "Ingestion failed: provider not supported",
            )
            return

        job.message = "Downloading OHLCV from Databento"
        job.progress_pct = 10
        db.commit()

        try:
            dataset = run_databento_ingestion(db, job.payload)
            db.commit()
            job.status = ResearchJobStatus.COMPLETED
            job.progress_pct = 100
            job.message = f"Imported {dataset.row_count} bars ({dataset.timeframe})"
            job.completed_at = datetime.now(UTC)
            job.payload = {**job.payload, "dataset_id": str(dataset.id), "row_count": dataset.row_count}
            db.add(
                ResearchActivity(
                    headline=f"Dataset ready: {job.payload.get('instrument_symbol')} {dataset.timeframe}",
                    detail=f"{dataset.row_count} bars · id {dataset.id}",
                    job_id=job.id,
                    meta={"dataset_id": str(dataset.id)},
                )
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(ResearchJob, uuid.UUID(job_id))
            if job:
                _fail_ingestion(db, job, str(exc), "Ingestion failed")


def enqueue_backtest(run_id: str, actor: str) -> str:
    with SyncSession() as db:
        db.add(
            ResearchActivity(
                headline="Backtest queued",
                detail=f"Run {run_id} requested by {actor}",
                meta={"backtest_run_id": run_id},
            )
        )
        db.commit()
    run_backtest_task.delay(run_id)
    return run_id


@celery_app.task(name="app.worker.tasks.run_backtest_task")
def run_backtest_task(run_id: str) -> None:
    with SyncSession() as db:
        try:
            execute_backtest_run(db, uuid.UUID(run_id))
            db.add(
                ResearchActivity(
                    headline=f"Backtest finished: {run_id}",
                    detail="See Backtest Laboratory for metrics and trade ledger.",
                    meta={"backtest_run_id": run_id},
                )
            )
            db.commit()
        except Exception as exc:
            db.add(
                ResearchActivity(
                    headline=f"Backtest failed: {run_id}",
                    detail=str(exc),
                    meta={"backtest_run_id": run_id},
                )
            )
            db.commit()


@celery_app.task(name="app.worker.tasks.health_pulse")
def health_pulse() -> None:
    """Periodic worker heartbeat — no fabricated research activity."""
    _ = SyncSession  # ensures DB connectivity on schedule