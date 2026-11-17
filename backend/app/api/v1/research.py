from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.research import ResearchActivity, ResearchJob
from app.models.user import User
from app.schemas.research import ResearchActivityOut, ResearchJobOut

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/activity", response_model=list[ResearchActivityOut])
async def research_activity(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, le=200),
) -> list[ResearchActivityOut]:
    result = await db.execute(
        select(ResearchActivity).order_by(ResearchActivity.created_at.desc()).limit(limit)
    )
    items = result.scalars().all()
    return [
        ResearchActivityOut(
            id=str(a.id),
            headline=a.headline,
            detail=a.detail,
            created_at=a.created_at.isoformat(),
        )
        for a in items
    ]


@router.get("/jobs", response_model=list[ResearchJobOut])
async def research_jobs(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, le=200),
) -> list[ResearchJobOut]:
    result = await db.execute(select(ResearchJob).order_by(ResearchJob.created_at.desc()).limit(limit))
    jobs = result.scalars().all()
    return [
        ResearchJobOut(
            id=str(j.id),
            kind=j.kind.value,
            status=j.status.value,
            title=j.title,
            message=j.message,
            progress_pct=j.progress_pct,
            created_at=j.created_at.isoformat(),
        )
        for j in jobs
    ]