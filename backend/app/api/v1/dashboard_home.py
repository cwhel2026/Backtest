from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import get_settings
from app.db.session import SyncSessionLocal
from app.models.user import User
from app.services.dashboard_home import build_home_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/home")
async def home_dashboard(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    symbols = [s.strip().upper() for s in settings.live_lab_symbols.split(",") if s.strip()]
    with SyncSessionLocal() as session:
        return build_home_dashboard(session, symbols=symbols)