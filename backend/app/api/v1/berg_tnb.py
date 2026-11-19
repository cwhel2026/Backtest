"""Berg TNB research API — timeline preview and strategy comparison."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.backtest.bars import load_bars
from app.backtest.berg_tnb.backtest import _setup_payload
from app.backtest.berg_tnb.pipeline import BergTnbEngine
from app.db.session import SyncSessionLocal, get_db
from app.models.backtest import BacktestRun
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.strategy import StrategyVersion
from app.models.user import User

router = APIRouter(prefix="/berg-tnb", tags=["berg-tnb"])


class TimelinePreviewRequest(BaseModel):
    dataset_id: str
    specification: dict


@router.get("/spec-template")
def spec_template():
    return {
        "entry": {
            "type": "berg_tnb_model_v1",
            "session_profile": "pdf_indices",
            "setup_preset": "new_york_setup",
            "fib_fakeout_ratio": "0.079",
            "entry_fib_ratio": "0.618",
            "entry_fib_ratios_experimental": ["0.500", "0.550", "0.595", "0.618"],
        },
        "exit_meta": {"profile": "structural_rr", "reward_risk": "2"},
        "exit_profiles": ["structural_rr", "fixed_ticks", "swing", "time_exit"],
        "session_profiles": ["pdf_indices", "pdf_forex", "cme_futures_research"],
        "pdf_note": "Primary PDF not in repository — see docs/BERG_TNB_MODEL.md",
    }


@router.post("/preview-timeline")
async def preview_timeline(
    body: TimelinePreviewRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    try:
        ds_id = uuid.UUID(body.dataset_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid dataset_id") from exc
    ds = await db.get(HistoricalDataset, ds_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    inst = await db.get(Instrument, ds.instrument_id) if ds.instrument_id else None
    if not inst:
        raise HTTPException(400, "Dataset missing instrument")

    with SyncSessionLocal() as sync:
        bars = load_bars(sync, ds.id)
        engine = BergTnbEngine(body.specification, bars, inst.tick_size)
        setups, orders = engine.run()
    return {
        "setups": [_setup_payload(s) for s in setups],
        "order_count": len(orders),
        "dataset_version": ds.version_tag,
        "checksum": ds.content_checksum,
    }


@router.get("/compare")
async def compare_runs(
    run_ids: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    ids = [x.strip() for x in run_ids.split(",") if x.strip()]
    rows: list[dict] = []
    for rid in ids:
        try:
            run = await db.get(BacktestRun, uuid.UUID(rid))
        except ValueError:
            continue
        if not run:
            continue
        ver = await db.get(StrategyVersion, run.strategy_version_id)
        entry_type = ((ver.specification or {}).get("entry") or {}).get("type") if ver else None
        m = run.metrics or {}
        rows.append(
            {
                "run_id": str(run.id),
                "entry_type": entry_type,
                "trade_count": m.get("trade_count"),
                "win_rate": m.get("win_rate"),
                "profit_factor": m.get("profit_factor"),
                "total_net_profit": m.get("total_net_profit"),
                "max_drawdown": m.get("max_drawdown"),
                "expectancy_per_trade": m.get("expectancy_per_trade"),
                "berg_setups": m.get("berg_setups"),
            }
        )
    return {"runs": rows, "note": "Compare equivalent dataset periods and cost assumptions only."}