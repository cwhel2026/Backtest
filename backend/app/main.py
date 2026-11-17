from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, PendingRollbackError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.bootstrap import bootstrap_database
from app.util.serde import integrity_hint

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with AsyncSessionLocal() as session:
        await bootstrap_database(session)
        await session.commit()
    logger.info("prop_edge_startup_complete")
    yield


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
        return {"status": "ok", "app": settings.app_name, "environment": settings.environment}

    @app.exception_handler(IntegrityError)
    async def db_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        hint = integrity_hint(exc)
        logger.exception("db_integrity_error", error=str(exc), hint=hint)
        detail = "Database could not save this run."
        if hint:
            detail += f" {hint}"
        detail += " Wait for the deploy to finish, then press Run prop search again."
        return JSONResponse(status_code=500, content={"detail": detail})

    @app.exception_handler(PendingRollbackError)
    async def db_pending_rollback(_request: Request, exc: PendingRollbackError) -> JSONResponse:
        logger.exception("db_pending_rollback", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": "Database session was interrupted after an error. Press Run prop search again."},
        )

    @app.exception_handler(Exception)
    async def unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        logger.exception("unhandled_api_error", error=str(exc))
        return JSONResponse(status_code=500, content={"detail": "Server error. Press Run prop search again in a few seconds."})

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()