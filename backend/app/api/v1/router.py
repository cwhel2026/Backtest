from fastapi import APIRouter

from app.api.v1 import auth, backtests, instruments, market_data, overview, research, strategies

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(overview.router)
api_router.include_router(instruments.router)
api_router.include_router(market_data.router)
api_router.include_router(strategies.router)
api_router.include_router(research.router)
api_router.include_router(backtests.router)