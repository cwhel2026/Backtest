import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.backtest import BacktestRun
from app.models.research import ResearchActivity
from app.models.user import User
from app.schemas.autopilot import AutopilotRunResponse, AutopilotStatus
from app.services.autonomous_cycle import run_autonomous_prop_cycle
from app.worker.tasks import autonomous_prop_cycle

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


@router.get("/status", response_model=AutopilotStatus)
async def autopilot_status(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AutopilotStatus:
    settings = get_settings()
    runs = (
        await db.execute(
            select(BacktestRun)
            .where(BacktestRun.status == "completed")
            .order_by(desc(BacktestRun.completed_at))
            .limit(20)
        )
    ).scalars().all()

    def score(r: BacktestRun) -> float:
        m = r.metrics or {}
        pf = m.get("profit_factor")
        if pf is not None:
            return float(pf)
        return float(m.get("total_net_profit") or 0)

    ranked = sorted(runs, key=score, reverse=True)[:5]
    top = [
        {
            "id": str(r.id),
            "strategy_id": str(r.strategy_id),
            "profit_factor": (r.metrics or {}).get("profit_factor"),
            "net_profit": (r.metrics or {}).get("total_net_profit"),
            "trade_count": (r.metrics or {}).get("trade_count"),
        }
        for r in ranked
    ]

    activity = (
        await db.execute(select(ResearchActivity).order_by(desc(ResearchActivity.created_at)).limit(8))
    ).scalars().all()
    recent = [
        {"headline": a.headline, "detail": a.detail, "created_at": a.created_at.isoformat()} for a in activity
    ]

    return AutopilotStatus(
        hourly_enabled=settings.autonomous_hourly_enabled,
        ai_configured=settings.ai_configured,
        message=(
            "Autopilot refreshes Yahoo data hourly, tests new strategies on MES/MNQ, "
            "and runs a live-style sim on recent bars — no broker account."
        ),
        top_backtests=top,
        recent_activity=recent,
    )


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