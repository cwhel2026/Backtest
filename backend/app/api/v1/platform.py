from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.session import SyncSessionLocal
from app.models.user import User
from app.services.platform_status import build_platform_status

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/status")
async def platform_status(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    with SyncSessionLocal() as session:
        return build_platform_status(session)