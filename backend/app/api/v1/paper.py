import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_sync_db
from app.models.instrument import Instrument
from app.models.strategy import StrategyDefinition
from app.models.user import User
from app.services.paper_book import enroll_strategy, paper_snapshot, tick_paper_book

router = APIRouter(prefix="/paper", tags=["paper"])


class EnrollBody(BaseModel):
    strategy_id: uuid.UUID


@router.get("/desk")
def paper_desk(_: User = Depends(get_current_user), db: Session = Depends(get_sync_db)) -> dict:
    snap = paper_snapshot(db)
    db.commit()
    return snap


@router.post("/tick")
def paper_tick(_: User = Depends(get_current_user), db: Session = Depends(get_sync_db)) -> dict:
    result = tick_paper_book(db)
    return {"tick": result, "desk": paper_snapshot(db)}


@router.post("/enroll")
def paper_enroll(
    body: EnrollBody,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_sync_db),
) -> dict:
    strategy = db.get(StrategyDefinition, body.strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    inst = db.get(Instrument, strategy.instrument_id)
    symbol = inst.symbol if inst else str((strategy.name or "UNK").split()[0])
    slot = enroll_strategy(db, strategy, symbol)
    if not slot:
        raise HTTPException(status_code=409, detail="Paper book is full or the sim account is breached.")
    db.commit()
    return {"slot_id": str(slot.id), "symbol": slot.symbol, "timeframe": slot.timeframe, "desk": paper_snapshot(db)}
