from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_sync_db
from app.models.user import User
from app.services.paper_book import paper_snapshot, tick_paper_book

router = APIRouter(prefix="/paper", tags=["paper"])


@router.get("/desk")
def paper_desk(_: User = Depends(get_current_user), db: Session = Depends(get_sync_db)) -> dict:
    snap = paper_snapshot(db)
    db.commit()
    return snap


@router.post("/tick")
def paper_tick(_: User = Depends(get_current_user), db: Session = Depends(get_sync_db)) -> dict:
    result = tick_paper_book(db)
    return {"tick": result, "desk": paper_snapshot(db)}
