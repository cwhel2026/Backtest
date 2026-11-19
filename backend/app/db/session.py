from collections.abc import AsyncGenerator, Generator
from contextlib import suppress

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)


def get_sync_db() -> Generator[Session, None, None]:
    db = SyncSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            with suppress(Exception):
                await session.rollback()
            raise
        try:
            if session.in_transaction():
                await session.commit()
        except Exception:
            with suppress(Exception):
                await session.rollback()
            raise


async def get_db_readonly() -> AsyncGenerator[AsyncSession, None]:
    """Login and other reads: never COMMIT a recovering connection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            with suppress(Exception):
                await session.rollback()