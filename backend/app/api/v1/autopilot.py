import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.enums import ResearchJobKind, ResearchJobStatus
from app.models.research import ResearchActivity, ResearchJob
from app.models.user import User
from app.schemas.autopilot import (
    AutopilotRunResponse,
    AutopilotStatus,
    BackgroundSearchStatus,
    CycleStats,
    LeaderboardEntry,
)
from app.services.autonomous_cycle import PROP_SEARCH_JOB_TITLE, job_is_stale, resolve_search_symbols
from app.services.research_jobs import add_job_with_activity_async
from app.services.leaderboard import leaderboard_entries_async
from app.util.serde import enum_value, normalize_created_by
from app.worker.tasks import run_prop_search_job

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


async def _queue_deep_prop_search(db: AsyncSession, actor: str) -> str:
    job_id = uuid.uuid4()
    actor_label = normalize_created_by(actor)
    job = ResearchJob(
        id=job_id,
        kind=ResearchJobKind.VALIDATION,
        status=ResearchJobStatus.QUEUED,
        title=PROP_SEARCH_JOB_TITLE,
        message="Queued — runs on the server (safe to close the app)",
        payload={"actor": actor_label, "actor_display": actor, "source": "manual"},
    )
    await add_job_with_activity_async(
        db,
        job,
        headline="Deep search queued",
        detail=f"Requested by {actor}. Worker will run walk-forward search in the background.",
    )
    await db.flush()
    return str(job_id)


@router.get("/status", response_model=AutopilotStatus)
async def autopilot_status(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AutopilotStatus:
    settings = get_settings()
    active_rows = (
        await db.execute(
            select(ResearchJob)
            .where(
                ResearchJob.title == PROP_SEARCH_JOB_TITLE,
                ResearchJob.status.in_((ResearchJobStatus.QUEUED, ResearchJobStatus.RUNNING)),
            )
        )
    ).scalars().all()
    stale_changed = False
    for stale in active_rows:
        if job_is_stale(stale):
            stale.status = ResearchJobStatus.FAILED
            stale.error = "Search stalled before it finished. Press Run prop search again."
            stale.completed_at = datetime.now(UTC)
            db.add(
                ResearchActivity(
                    headline="Deep search stalled",
                    detail=stale.error,
                    job_id=stale.id,
                )
            )
            stale_changed = True
    if stale_changed:
        await db.commit()

    profitable = await leaderboard_entries_async(db, limit=12, profitable_only=True)
    recent_tests = await leaderboard_entries_async(db, limit=6, profitable_only=False)

    activity = (
        await db.execute(select(ResearchActivity).order_by(desc(ResearchActivity.created_at)).limit(10))
    ).scalars().all()
    recent = [
        {"headline": a.headline, "detail": a.detail, "created_at": a.created_at.isoformat()} for a in activity
    ]

    latest_job = (
        await db.execute(
            select(ResearchJob)
            .where(ResearchJob.title == PROP_SEARCH_JOB_TITLE)
            .order_by(desc(ResearchJob.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    background_search = None
    if latest_job:
        background_search = BackgroundSearchStatus(
            job_id=str(latest_job.id),
            status=enum_value(latest_job.status),
            message=latest_job.message or "",
            progress_pct=latest_job.progress_pct or 0,
            started_at=latest_job.started_at.isoformat() if latest_job.started_at else None,
            error=latest_job.error,
        )

    last_cycle = next((a for a in activity if "search" in a.headline.lower()), None)
    cycle_stats = CycleStats(
        last_cycle_detail=last_cycle.detail if last_cycle else None,
        profitable_count=len(profitable),
        tests_run=0,
    )
    if last_cycle and last_cycle.detail:
        if "Tested " in last_cycle.detail:
            try:
                part = last_cycle.detail.split("Tested ", 1)[1].split(" variants", 1)[0]
                cycle_stats.tests_run = int(part)
            except ValueError:
                pass

    return AutopilotStatus(
        hourly_enabled=settings.autonomous_hourly_enabled,
        ai_configured=settings.ai_configured,
        search_symbols=list(resolve_search_symbols()),
        message=(
            "Always-on prop desk: hourly search on Nasdaq + S&P, walk-forward backtests, "
            "then a paper book that opens and closes trades on new 5-minute bars under "
            "prop-style daily loss, trailing drawdown, and profit target. "
            "Simulated only — delayed data, not a broker."
        ),
        background_search=background_search,
        profitable_candidates=[LeaderboardEntry(**e) for e in profitable],
        recent_tests=[LeaderboardEntry(**e) for e in recent_tests],
        recent_activity=recent,
        cycle_stats=cycle_stats,
    )


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def prop_leaderboard(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    profitable_only: bool = Query(True),
    limit: int = Query(25, le=100),
) -> list[LeaderboardEntry]:
    rows = await leaderboard_entries_async(db, limit=limit, profitable_only=profitable_only)
    return [LeaderboardEntry(**e) for e in rows]


@router.post("/run", response_model=AutopilotRunResponse)
async def run_autopilot_now(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    restart: bool = Query(False),
) -> AutopilotRunResponse:
    active_job = (
        await db.execute(
            select(ResearchJob)
            .where(
                ResearchJob.title == PROP_SEARCH_JOB_TITLE,
                ResearchJob.status.in_((ResearchJobStatus.QUEUED, ResearchJobStatus.RUNNING)),
            )
            .order_by(desc(ResearchJob.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_job and (restart or job_is_stale(active_job)):
        active_job.status = ResearchJobStatus.FAILED
        active_job.error = "Replaced by a new search."
        active_job.completed_at = datetime.now(UTC)
        await db.commit()
        active_job = None
    if active_job:
        return AutopilotRunResponse(
            job_id=str(active_job.id),
            status=enum_value(active_job.status),
            mode="already_active",
        )

    job_id = await _queue_deep_prop_search(db, user.email)
    # Keep the heavy search off the web process. Running it inline was stalling
    # every other request and the proxy answered "Internal Server Error".
    try:
        run_prop_search_job.delay(job_id)
        mode = "celery"
    except Exception:
        import threading

        threading.Thread(
            target=run_prop_search_job,
            args=(job_id,),
            daemon=True,
            name="prop-search",
        ).start()
        mode = "thread"
    return AutopilotRunResponse(job_id=job_id, status="queued", mode=mode)