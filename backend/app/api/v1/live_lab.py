"""Live Strategy Lab API."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_sync_db
from app.models.user import User
from app.models.enums import ForwardTestState
from app.models.live_lab import ForwardTestRun
from app.models.strategy import StrategyDefinition
from app.services.live_lab.ledger import list_ledger_events
from app.services.live_lab.market_data.registry import get_market_data_adapter
from app.services.live_lab.promotion import evaluate_historical_validation
from app.services.live_lab.service import dashboard_summary, start_forward_test, tick_live_strategy_lab

router = APIRouter(prefix="/live-lab", tags=["live-lab"])


class StartForwardTestBody(BaseModel):
    strategy_id: UUID
    symbol: str = Field(pattern=r"^(MNQ|MES|MGC)$")
    experimental: bool = False


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_sync_db), _user: User = Depends(get_current_user)):
    return dashboard_summary(db)


@router.get("/providers")
def list_providers(db: Session = Depends(get_sync_db), _user: User = Depends(get_current_user)):
    from app.services.live_lab.market_data.stubs import CmeWebSocketAdapter, DatabentoLiveAdapter, IbkrTwsAdapter

    adapter = get_market_data_adapter(db)
    out = [{"id": adapter.provider_id, **adapter.describe()}]
    for stub in (DatabentoLiveAdapter(), IbkrTwsAdapter(), CmeWebSocketAdapter()):
        out.append({"id": stub.provider_id, **stub.describe()})
    return {"providers": out, "active": adapter.provider_id}


@router.post("/forward-tests/start")
def api_start_forward_test(
    body: StartForwardTestBody,
    db: Session = Depends(get_sync_db),
    user: User = Depends(get_current_user),
):
    strat = db.get(StrategyDefinition, body.strategy_id)
    if not strat:
        raise HTTPException(404, detail="Strategy not found")
    try:
        run = start_forward_test(
            db,
            body.strategy_id,
            symbol=body.symbol,
            experimental=body.experimental,
            actor=getattr(user, "email", "user"),
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    return {"run_id": str(run.id), "state": run.research_state.value, "experimental": run.experimental}


@router.post("/forward-tests/{run_id}/pause")
def pause_forward_test(run_id: UUID, db: Session = Depends(get_sync_db), _user: User = Depends(get_current_user)):
    run = db.get(ForwardTestRun, run_id)
    if not run:
        raise HTTPException(404, detail="Run not found")
    run.research_state = ForwardTestState.FORWARD_TEST_PAUSED
    run.pause_reason = "Paused by user"
    db.commit()
    return {"ok": True}


@router.post("/forward-tests/{run_id}/resume")
def resume_forward_test(run_id: UUID, db: Session = Depends(get_sync_db), _user: User = Depends(get_current_user)):
    run = db.get(ForwardTestRun, run_id)
    if not run:
        raise HTTPException(404, detail="Run not found")
    run.research_state = ForwardTestState.FORWARD_TEST_RUNNING
    run.pause_reason = None
    db.commit()
    return {"ok": True}


@router.get("/forward-tests/{run_id}")
def get_forward_test(run_id: UUID, db: Session = Depends(get_sync_db), _user: User = Depends(get_current_user)):
    run = db.get(ForwardTestRun, run_id)
    if not run:
        raise HTTPException(404, detail="Run not found")
    strat = db.get(StrategyDefinition, run.strategy_id)
    events = list_ledger_events(db, run_id, limit=100)
    ok, reasons, gates = evaluate_historical_validation(db, run.strategy_id)
    return {
        "run": {
            "id": str(run.id),
            "strategy_name": strat.name if strat else None,
            "symbol": run.symbol,
            "timeframe": run.timeframe,
            "research_state": run.research_state.value,
            "experimental": run.experimental,
            "frozen_specification": run.frozen_specification,
            "net_pnl": float(run.net_pnl),
            "equity": float(run.equity),
            "trade_count": run.trade_count,
            "max_drawdown": float(run.max_drawdown),
            "last_data_exchange_ts": run.last_data_exchange_ts.isoformat() if run.last_data_exchange_ts else None,
        },
        "validation": {"passed": ok, "reasons": reasons, "gates": gates},
        "ledger": [
            {
                "event_type": e.event_type,
                "payload": e.payload,
                "exchange_ts": e.exchange_ts.isoformat() if e.exchange_ts else None,
                "decision_ts": e.decision_ts.isoformat() if e.decision_ts else None,
                "sequence": e.sequence,
            }
            for e in events
        ],
    }


@router.post("/tick")
def manual_tick(db: Session = Depends(get_sync_db), _user: User = Depends(get_current_user)):
    result = tick_live_strategy_lab(db)
    db.commit()
    return result