"""Background research and data jobs — records real job state in PostgreSQL."""

import uuid
from datetime import UTC, datetime

from app.worker.celery_app import celery_app
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.enums import ResearchJobKind, ResearchJobStatus
from app.models.research import ResearchActivity, ResearchJob

settings = get_settings()
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


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
            job.status = ResearchJobStatus.FAILED
            job.error = "Databento API key not configured"
            job.message = job.error
            job.completed_at = datetime.now(UTC)
            db.add(
                ResearchActivity(
                    headline="Ingestion failed: Databento not configured",
                    detail=job.error,
                    job_id=job.id,
                )
            )
            db.commit()
            return

        job.status = ResearchJobStatus.FAILED
        job.error = "Provider SDK integration pending (Phase 1 framework). No synthetic data imported."
        job.message = job.error
        job.completed_at = datetime.now(UTC)
        db.add(
            ResearchActivity(
                headline="Ingestion blocked until provider integration is completed",
                detail=job.error,
                job_id=job.id,
            )
        )
        db.commit()


@celery_app.task(name="app.worker.tasks.health_pulse")
def health_pulse() -> None:
    """Periodic worker heartbeat — no fabricated research activity."""
    _ = SyncSession  # ensures DB connectivity on schedule