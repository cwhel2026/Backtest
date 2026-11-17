from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.enums import DataProviderStatus, ResearchJobStatus
from app.models.market_data import DataProvider
from app.models.research import ResearchActivity, ResearchJob
from app.models.user import User
from app.services.autonomous_cycle import PROP_SEARCH_JOB_TITLE
from app.services.instruments import seed_instruments
from app.services.strategy_library import seed_strategy_library
from app.services.market_data.providers import PROVIDER_REGISTRY


async def bootstrap_database(session: AsyncSession) -> None:
    await seed_instruments(session)
    await seed_strategy_library(session)
    await _seed_providers(session)
    await _seed_admin_user(session)
    await _clear_searches_interrupted_by_restart(session)


async def _clear_searches_interrupted_by_restart(session: AsyncSession) -> None:
    """A deploy kills the old process. Any search still marked running is not actually running."""
    rows = (
        await session.execute(
            select(ResearchJob).where(
                ResearchJob.title == PROP_SEARCH_JOB_TITLE,
                ResearchJob.status.in_((ResearchJobStatus.QUEUED, ResearchJobStatus.RUNNING)),
            )
        )
    ).scalars().all()
    for job in rows:
        job.status = ResearchJobStatus.FAILED
        job.error = "Stopped because the server restarted. Press Run prop search to start a new one."
        job.completed_at = datetime.now(UTC)
        session.add(
            ResearchActivity(
                headline="Search stopped on restart",
                detail=job.error,
                job_id=job.id,
            )
        )


async def _seed_providers(session: AsyncSession) -> None:
    settings = get_settings()
    for slug, provider in PROVIDER_REGISTRY.items():
        result = await session.execute(select(DataProvider).where(DataProvider.slug == slug))
        row = result.scalar_one_or_none()
        health = await provider.health()
        status = DataProviderStatus.NOT_CONFIGURED
        if health.state.value == "configured":
            status = DataProviderStatus.CONFIGURED
        elif health.state.value == "connected":
            status = DataProviderStatus.CONNECTED
        if not row:
            session.add(
                DataProvider(
                    slug=slug,
                    display_name=provider.display_name,
                    status=status,
                    config_hint=health.message,
                    capabilities=health.capabilities,
                )
            )
        else:
            row.status = status
            row.config_hint = health.message


async def _seed_admin_user(session: AsyncSession) -> None:
    """Ensure Railway/env admin exists and password matches env (updates on each API boot)."""
    settings = get_settings()
    email = settings.initial_admin_email.strip().lower()
    result = await session.execute(select(User).where(func.lower(User.email) == email))
    users = result.scalars().all()
    hashed = hash_password(settings.initial_admin_password)
    keeper = next((u for u in users if u.email == email), None)
    if keeper is None and users:
        keeper = users[0]
    if keeper and len(users) > 1:
        doomed = [u.id for u in users if u.id != keeper.id]
        await session.execute(delete(User).where(User.id.in_(doomed)))
        await session.flush()
    user = keeper
    if user:
        user.email = email
        user.hashed_password = hashed
        user.is_active = True
        user.is_superuser = True
        return
    session.add(
        User(
            email=email,
            hashed_password=hashed,
            is_superuser=True,
        )
    )