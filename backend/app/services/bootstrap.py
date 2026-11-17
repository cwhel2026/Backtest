from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.enums import DataProviderStatus
from app.models.market_data import DataProvider
from app.models.user import User
from app.services.instruments import seed_instruments
from app.services.strategy_library import seed_strategy_library
from app.services.market_data.providers import PROVIDER_REGISTRY


async def bootstrap_database(session: AsyncSession) -> None:
    await seed_instruments(session)
    await seed_strategy_library(session)
    await _seed_providers(session)
    await _seed_admin_user(session)


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
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    hashed = hash_password(settings.initial_admin_password)
    if user:
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