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
from app.services.ai_research_runner import count_ai_jobs_today, run_ai_hypothesis_job
from app.services.research_jobs import add_job_with_activity
from app.services.autonomous_cycle import (
    PROP_SEARCH_JOB_TITLE,
    find_active_prop_search_job,
    run_autonomous_prop_cycle,
)
from app.services.market_data.ingestion_runner import (
    run_databento_ingestion,
    run_ibkr_ingestion,
    run_yahoo_ingestion,
)

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


def create_ingestion_job(meta: dict, actor: str) -> str:
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
        add_job_with_activity(
            db,
            job,
            headline=f"Queued ingestion for {meta.get('instrument_symbol')} ({meta.get('timeframe')})",
            detail=f"Requested by {actor}",
        )
        db.commit()
    return job_id


def enqueue_data_ingestion(meta: dict, actor: str) -> str:
    job_id = create_ingestion_job(meta, actor)
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

        if provider not in ("yahoo", "databento", "ibkr"):
            _fail_ingestion(
                db,
                job,
                f"Provider {provider} is not supported for automated ingestion yet.",
                "Ingestion failed: provider not supported",
            )
            return

        if provider == "ibkr" and not settings_ref.ibkr_configured:
            _fail_ingestion(db, job, "IBKR_HOST not configured", "Ingestion failed: IBKR not configured")
            return

        label = {"yahoo": "Yahoo Finance", "databento": "Databento", "ibkr": "IBKR Gateway"}[provider]
        job.message = f"Downloading OHLCV from {label}"
        job.progress_pct = 10
        db.commit()

        try:
            if provider == "yahoo":
                dataset = run_yahoo_ingestion(db, job.payload)
            elif provider == "ibkr":
                dataset = run_ibkr_ingestion(db, job.payload)
            else:
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


def enqueue_ai_hypothesis(meta: dict, actor: str) -> str:
    job_id = str(uuid.uuid4())
    with SyncSession() as db:
        settings_ref = get_settings()
        if count_ai_jobs_today(db) >= settings_ref.max_experiments_per_day:
            raise ValueError(f"Daily AI experiment limit ({settings_ref.max_experiments_per_day}) reached")

        job = ResearchJob(
            id=uuid.UUID(job_id),
            kind=ResearchJobKind.AI_HYPOTHESIS,
            status=ResearchJobStatus.QUEUED,
            title=f"AI hypothesis: {meta.get('instrument_symbol')}",
            message="Queued",
            payload={**meta, "actor": actor},
        )
        add_job_with_activity(
            db,
            job,
            headline=f"AI research queued for {meta.get('instrument_symbol')}",
            detail=(meta.get("prompt") or "")[:280],
        )
        db.commit()
    run_ai_hypothesis_task.delay(job_id)
    return job_id


@celery_app.task(name="app.worker.tasks.run_ai_hypothesis_task")
def run_ai_hypothesis_task(job_id: str) -> None:
    with SyncSession() as db:
        job = db.get(ResearchJob, uuid.UUID(job_id))
        if not job:
            return
        job.status = ResearchJobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.message = "Generating DSL specification"
        job.progress_pct = 20
        db.commit()
        try:
            strategy, backtest_run_id = run_ai_hypothesis_job(db, job)
            actor = job.payload.get("actor", "system")
            if backtest_run_id:
                db.commit()
                enqueue_backtest(backtest_run_id, actor=actor)
            job.status = ResearchJobStatus.COMPLETED
            job.progress_pct = 100
            job.message = f"Strategy created: {strategy.name}"
            job.completed_at = datetime.now(UTC)
            db.add(
                ResearchActivity(
                    headline=f"Strategy generated: {strategy.name}",
                    detail=f"Mode {job.payload.get('generation_mode', 'heuristic')} · id {strategy.id}",
                    job_id=job.id,
                    meta={"strategy_id": str(strategy.id)},
                )
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(ResearchJob, uuid.UUID(job_id))
            if job:
                job.status = ResearchJobStatus.FAILED
                job.error = str(exc)
                job.message = str(exc)
                job.completed_at = datetime.now(UTC)
                db.add(
                    ResearchActivity(
                        headline="AI research failed",
                        detail=str(exc),
                        job_id=job.id,
                    )
                )
                db.commit()


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


def create_prop_search_job(actor: str) -> str:
    from app.util.serde import normalize_created_by

    job_id = str(uuid.uuid4())
    actor_label = normalize_created_by(actor)
    with SyncSession() as db:
        job = ResearchJob(
            id=uuid.UUID(job_id),
            kind=ResearchJobKind.VALIDATION,
            status=ResearchJobStatus.QUEUED,
            title=PROP_SEARCH_JOB_TITLE,
            message="Queued — runs on the server (safe to close the app)",
            payload={"actor": actor_label, "actor_display": actor, "source": "manual"},
        )
        add_job_with_activity(
            db,
            job,
            headline="Deep search queued",
            detail=f"Requested by {actor}. Worker will run walk-forward search in the background.",
        )
        db.commit()
    return job_id


def enqueue_prop_search(actor: str) -> tuple[str, str]:
    """Return (job_id, disposition) where disposition is queued | already_active."""
    with SyncSession() as db:
        active = find_active_prop_search_job(db)
        if active:
            return str(active.id), "already_active"
    job_id = create_prop_search_job(actor)
    run_prop_search_job.delay(job_id)
    return job_id, "queued"


@celery_app.task(name="app.worker.tasks.run_prop_search_job")
def run_prop_search_job(job_id: str) -> None:
    from app.services.search_progress import merge_search_progress

    with SyncSession() as db:
        jid = uuid.UUID(job_id)
        job = db.execute(
            select(ResearchJob).where(ResearchJob.id == jid).with_for_update()
        ).scalar_one_or_none()
        if not job:
            return
        if job.status != ResearchJobStatus.QUEUED:
            return
        job.status = ResearchJobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.message = "Search started on the server"
        merge_search_progress(job, phase="starting")
        actor = (job.payload or {}).get("actor", "autopilot")
        db.commit()
        run_autonomous_prop_cycle(db, actor=actor, job_id=job_id)


@celery_app.task(name="app.worker.tasks.autonomous_prop_cycle")
def autonomous_prop_cycle() -> None:
    settings_ref = get_settings()
    if not settings_ref.autonomous_hourly_enabled:
        return
    with SyncSession() as db:
        if find_active_prop_search_job(db):
            return
        run_autonomous_prop_cycle(db, actor="hourly_autopilot")


@celery_app.task(name="app.worker.tasks.paper_forward_tick")
def paper_forward_tick() -> None:
    from app.services.paper_book import tick_paper_book

    with SyncSession() as db:
        tick_paper_book(db)