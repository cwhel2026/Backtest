from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.enums import ResearchJobStatus, StrategyLifecycle
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.research import ResearchJob
from app.models.strategy import StrategyDefinition
from app.models.user import User
from app.schemas.market_data import ProviderHealthOut
from app.schemas.overview import OverviewStats
from app.services.market_data.providers import all_provider_health

router = APIRouter(prefix="/overview", tags=["overview"])


@router.get("/stats", response_model=OverviewStats)
async def overview_stats(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OverviewStats:
    settings = get_settings()
    instruments = (
        await db.execute(select(func.count()).select_from(Instrument).where(Instrument.is_active))
    ).scalar_one()
    strategies = (await db.execute(select(func.count()).select_from(StrategyDefinition))).scalar_one()
    validated = (
        await db.execute(
            select(func.count())
            .select_from(StrategyDefinition)
            .where(
                StrategyDefinition.lifecycle.in_(
                    [
                        StrategyLifecycle.HISTORICALLY_VALIDATED,
                        StrategyLifecycle.PAPER_VALIDATED,
                        StrategyLifecycle.ELIGIBLE_FOR_APPROVAL,
                    ]
                )
            )
        )
    ).scalar_one()
    paper = (
        await db.execute(
            select(func.count())
            .select_from(StrategyDefinition)
            .where(StrategyDefinition.lifecycle == StrategyLifecycle.PAPER_TRADING)
        )
    ).scalar_one()
    rejected = (
        await db.execute(
            select(func.count())
            .select_from(StrategyDefinition)
            .where(StrategyDefinition.lifecycle == StrategyLifecycle.REJECTED)
        )
    ).scalar_one()
    active_jobs = (
        await db.execute(
            select(func.count())
            .select_from(ResearchJob)
            .where(ResearchJob.status == ResearchJobStatus.RUNNING)
        )
    ).scalar_one()
    queued_jobs = (
        await db.execute(
            select(func.count())
            .select_from(ResearchJob)
            .where(ResearchJob.status == ResearchJobStatus.QUEUED)
        )
    ).scalar_one()
    datasets = (await db.execute(select(func.count()).select_from(HistoricalDataset))).scalar_one()
    providers = await all_provider_health()
    return OverviewStats(
        instruments_count=instruments,
        strategies_total=strategies,
        strategies_validated=validated,
        strategies_paper=paper,
        strategies_rejected=rejected,
        active_research_jobs=active_jobs,
        queued_research_jobs=queued_jobs,
        datasets_count=datasets,
        data_providers=[
            ProviderHealthOut(
                slug=p.slug,
                display_name=p.display_name,
                state=p.state.value,
                message=p.message,
                capabilities=p.capabilities,
            )
            for p in providers
        ],
        ai_research_enabled=settings.ai_research_enabled,
        ai_configured=settings.ai_configured,
    )