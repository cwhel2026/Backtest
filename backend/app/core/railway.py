"""Normalize Railway-provided connection URLs for SQLAlchemy and Celery."""


def to_async_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


def to_sync_database_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def celery_urls_from_redis(redis_url: str) -> tuple[str, str]:
    """Single Redis instance on Railway — broker and result backend share the URL."""
    base = redis_url.rstrip("/")
    if base.endswith(("/0", "/1", "/2")):
        return base, base
    return f"{base}/0", f"{base}/0"