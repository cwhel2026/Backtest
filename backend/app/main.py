from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.bootstrap import bootstrap_database

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

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()