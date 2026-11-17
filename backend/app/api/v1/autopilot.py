import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.research import ResearchActivity
from app.models.user import User
from app.schemas.autopilot import AutopilotRunResponse, AutopilotStatus, CycleStats, LeaderboardEntry
from app.services.autonomous_cycle import resolve_search_symbols, run_autonomous_prop_cycle
from app.services.leaderboard import leaderboard_entries_async
from app.worker.tasks import autonomous_prop_cycle

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


@router.get("/status", response_model=AutopilotStatus)
async def autopilot_status(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AutopilotStatus:
    settings = get_settings()
    profitable = await leaderboard_entries_async(db, limit=12, profitable_only=True)

    activity = (
        await db.execute(select(ResearchActivity).order_by(desc(ResearchActivity.created_at)).limit(10))
    ).scalars().all()
    recent = [
        {"headline": a.headline, "detail": a.detail, "created_at": a.created_at.isoformat()} for a in activity
    ]

    last_cycle = next((a for a in activity if "cycle" in a.headline.lower()), None)
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
            "Deep search on S&P + Nasdaq (MES/MNQ/NQ/ES by default): 120+ combos per symbol, "
            "35 days of 5m data, walk-forward validation, OOS-profitable only."
        ),
        profitable_candidates=[LeaderboardEntry(**e) for e in profitable],
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
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> AutopilotRunResponse:
    job_id = str(uuid.uuid4())
    try:
        autonomous_prop_cycle.delay()
        return AutopilotRunResponse(job_id=job_id, status="queued", mode="celery")
    except Exception:
        def _inline() -> None:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker

            settings = get_settings()
            engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
            Session = sessionmaker(bind=engine)
            with Session() as session:
                run_autonomous_prop_cycle(session, actor=user.email)

        background_tasks.add_task(_inline)
        return AutopilotRunResponse(job_id=None, status="running", mode="inline")