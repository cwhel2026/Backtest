"""Helpers for creating research jobs + feed rows in FK-safe order."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.research import ResearchActivity, ResearchJob


def add_job_with_activity(
    session: Session,
    job: ResearchJob,
    *,
    headline: str,
    detail: str,
) -> ResearchActivity:
    session.add(job)
    session.flush()
    activity = ResearchActivity(headline=headline, detail=detail, job_id=job.id)
    session.add(activity)
    return activity


async def add_job_with_activity_async(
    session: AsyncSession,
    job: ResearchJob,
    *,
    headline: str,
    detail: str,
) -> ResearchActivity:
    session.add(job)
    await session.flush()
    activity = ResearchActivity(headline=headline, detail=detail, job_id=job.id)
    session.add(activity)
    return activity