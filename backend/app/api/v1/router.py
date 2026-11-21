from fastapi import APIRouter

from app.api.v1 import (
    ai_arena,
    auth,
    autopilot,
    backtests,
    berg_tnb,
    dashboard_home,
    instruments,
    live_lab,
    market_data,
    overview,
    paper,
    platform,
    research,
    scanner,
    strategies,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(overview.router)
api_router.include_router(autopilot.router)
api_router.include_router(paper.router)
api_router.include_router(instruments.router)
api_router.include_router(market_data.router)
api_router.include_router(strategies.router)
api_router.include_router(research.router)
api_router.include_router(backtests.router)
api_router.include_router(berg_tnb.router)
api_router.include_router(live_lab.router)
api_router.include_router(scanner.router)
api_router.include_router(platform.router)
api_router.include_router(dashboard_home.router)
api_router.include_router(ai_arena.router)