import asyncio
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError, PendingRollbackError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.bootstrap import bootstrap_database
from app.util.db_errors import (
    DISK_FULL_MESSAGE,
    POSTGRES_RECOVERY_MESSAGE,
    RETRY_AFTER_DB_ERROR,
    compact_error,
    is_disk_full,
    is_postgres_recovery,
)
from app.util.db_wait import is_retryable_db, run_alembic_upgrade
from app.util.serde import integrity_hint

logger = structlog.get_logger()


async def bring_database_up() -> None:
    """Migrate + seed, retrying while Postgres is in crash recovery."""
    delay = 2.0
    while True:
        try:
            await asyncio.to_thread(run_alembic_upgrade)
            async with AsyncSessionLocal() as session:
                await bootstrap_database(session)
                await session.commit()
            logger.info("prop_edge_startup_complete")
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not is_retryable_db(exc):
                logger.exception("bootstrap_failed", error=compact_error(exc))
            else:
                logger.warning("database_not_ready", error=compact_error(exc))
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 15.0)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(bring_database_up())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        database = "ok"
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            database = compact_error(exc)
        return {
            "status": "ok" if database == "ok" else "degraded",
            "app": settings.app_name,
            "environment": settings.environment,
            "database": database,
        }

    @app.exception_handler(IntegrityError)
    async def db_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        hint = integrity_hint(exc)
        logger.exception("db_integrity_error", error=str(exc), hint=hint)
        detail = "Database could not save this run."
        if hint:
            detail += f" {hint}"
        detail += f" {RETRY_AFTER_DB_ERROR}"
        return JSONResponse(status_code=500, content={"detail": detail})

    @app.exception_handler(OperationalError)
    async def db_operational(_request: Request, exc: OperationalError) -> JSONResponse:
        logger.exception("db_operational_error", error=str(exc))
        if is_postgres_recovery(exc):
            return JSONResponse(status_code=503, content={"detail": POSTGRES_RECOVERY_MESSAGE})
        if is_disk_full(exc):
            return JSONResponse(status_code=507, content={"detail": DISK_FULL_MESSAGE})
        return JSONResponse(status_code=503, content={"detail": compact_error(exc)})

    @app.exception_handler(PendingRollbackError)
    async def db_pending_rollback(_request: Request, exc: PendingRollbackError) -> JSONResponse:
        logger.exception("db_pending_rollback", error=str(exc))
        if is_postgres_recovery(exc) or is_disk_full(exc):
            return JSONResponse(status_code=503, content={"detail": compact_error(exc)})
        return JSONResponse(
            status_code=503,
            content={"detail": compact_error(exc) or RETRY_AFTER_DB_ERROR},
        )

    @app.exception_handler(Exception)
    async def unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        logger.exception("unhandled_api_error", error=str(exc))
        if is_disk_full(exc):
            return JSONResponse(status_code=507, content={"detail": DISK_FULL_MESSAGE})
        if is_postgres_recovery(exc):
            return JSONResponse(status_code=503, content={"detail": POSTGRES_RECOVERY_MESSAGE})
        return JSONResponse(status_code=500, content={"detail": compact_error(exc) or RETRY_AFTER_DB_ERROR})

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()