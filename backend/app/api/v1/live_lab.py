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
    from app.services.live_lab.market_data.ibkr_stream import IbkrStreamAdapter
    from app.services.live_lab.market_data.stubs import CmeWebSocketAdapter, DatabentoLiveAdapter, IbkrTwsAdapter

    adapter = get_market_data_adapter(db)
    out = [{"id": adapter.provider_id, **adapter.describe()}]
    ibkr = IbkrStreamAdapter()
    out.append({"id": ibkr.provider_id, **ibkr.describe(), "connectivity_check": ibkr.verify_connectivity()})
    for stub in (DatabentoLiveAdapter(), IbkrTwsAdapter(), CmeWebSocketAdapter()):
        out.append({"id": stub.provider_id, **stub.describe()})
    return {"providers": out, "active": adapter.provider_id}


@router.get("/candles")
def live_candles(
    symbol: str,
    timeframe: str = "5m",
    limit: int = 300,
    db: Session = Depends(get_sync_db),
    _user: User = Depends(get_current_user),
):
    from app.services.live_lab.candle_engine import load_closed_bars

    bars = load_closed_bars(db, symbol.upper(), timeframe, limit=limit)
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "bars": [
            {
                "ts": b.ts.isoformat(),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": b.volume,
            }
            for b in bars
        ],
    }


@router.get("/forward-tests/{run_id}/chart")
def forward_test_chart(run_id: UUID, db: Session = Depends(get_sync_db), _user: User = Depends(get_current_user)):
    run = db.get(ForwardTestRun, run_id)
    if not run:
        raise HTTPException(404, detail="Run not found")
    from app.services.live_lab.candle_engine import load_closed_bars

    bars = load_closed_bars(db, run.symbol, run.timeframe, limit=400)
    events = list_ledger_events(db, run_id, limit=300)
    trades = [e for e in events if e.event_type == "trade_closed"]
    markers = []
    for e in events:
        if e.event_type in ("order_placed", "order_filled", "signal_entry"):
            markers.append(
                {"ts": e.exchange_ts.isoformat() if e.exchange_ts else None, "type": e.event_type, "payload": e.payload}
            )
    equity = []
    eq = float(run.starting_equity)
    equity.append({"ts": run.started_at.isoformat() if run.started_at else None, "equity": eq})
    for t in reversed(trades):
        pnl = float((t.payload or {}).get("net_pnl") or 0)
        eq += pnl
        equity.append({"ts": t.exchange_ts.isoformat() if t.exchange_ts else None, "equity": eq})
    from sqlalchemy import select

    from app.models.live_lab import PaperBrokerOrder

    orders = db.execute(select(PaperBrokerOrder).where(PaperBrokerOrder.run_id == run_id)).scalars().all()
    return {
        "bars": [
            {"ts": b.ts.isoformat(), "open": float(b.open), "high": float(b.high), "low": float(b.low), "close": float(b.close)}
            for b in bars
        ],
        "markers": markers,
        "equity_curve": equity,
        "open_position": ((run.runner_state or {}).get("executor") or run.runner_state or {}).get("open_position"),
        "pending_orders": ((run.runner_state or {}).get("executor") or run.runner_state or {}).get("pending", []),
        "strategy_phase": (run.runner_state or {}).get("strategy_phase"),
        "runner_state_version": (run.runner_state or {}).get("version"),
        "paper_orders": [
            {
                "client_order_id": o.client_order_id,
                "state": o.state.value,
                "side": o.side,
                "order_type": o.order_type,
                "limit_price": float(o.limit_price) if o.limit_price is not None else None,
                "stop_price": float(o.stop_price) if o.stop_price is not None else None,
                "uncertainty_tags": o.uncertainty_tags,
            }
            for o in orders
        ],
        "run": {
            "net_pnl": float(run.net_pnl),
            "equity": float(run.equity),
            "trade_count": run.trade_count,
        },
    }


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
            "strategy_phase": (run.runner_state or {}).get("strategy_phase"),
            "runner_state_version": (run.runner_state or {}).get("version"),
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


@router.get("/certification/dashboard")
def certification_dashboard(db: Session = Depends(get_sync_db), _user: User = Depends(get_current_user)):
    from sqlalchemy import desc, select

    from app.models.certification import AccuracyCertificationRun

    rows = db.execute(select(AccuracyCertificationRun).order_by(desc(AccuracyCertificationRun.created_at)).limit(10)).scalars().all()
    latest = rows[0] if rows else None
    from app.services.live_lab.certification.strategy_readiness import strategy_readiness_matrix

    return {
        "strategy_readiness": strategy_readiness_matrix(),
        "latest": (
            {
                "status": latest.status,
                "symbol": latest.symbol,
                "replay_fingerprint": latest.replay_fingerprint,
                "detail": latest.detail,
                "payload": latest.payload,
                "created_at": latest.created_at.isoformat(),
            }
            if latest
            else None
        ),
        "history": [
            {
                "id": str(r.id),
                "status": r.status,
                "symbol": r.symbol,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "disclaimer": "Certification confirms software tests passed, not profitability or live fill guarantees.",
    }


@router.post("/certification/run")
def run_certification(
    symbol: str = "MES",
    db: Session = Depends(get_sync_db),
    _user: User = Depends(get_current_user),
):
    from app.services.live_lab.certification.runner import run_accuracy_certification

    if symbol.upper() not in {"MNQ", "MES", "MGC"}:
        raise HTTPException(400, detail="Symbol must be MNQ, MES, or MGC")
    row = run_accuracy_certification(db, symbol=symbol.upper())
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "detail": row.detail,
        "payload": row.payload,
        "replay_fingerprint": row.replay_fingerprint,
    }