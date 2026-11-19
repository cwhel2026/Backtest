from fastapi import APIRouter

from app.api.v1 import auth, autopilot, backtests, berg_tnb, instruments, market_data, overview, paper, research, strategies

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