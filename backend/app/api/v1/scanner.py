from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.scanner import ScannerSetup
from app.models.user import User
from app.schemas.scanner import ScannerSetupList, ScannerSetupOut

router = APIRouter(prefix="/scanner", tags=["scanner"])


def _row_out(s: ScannerSetup) -> ScannerSetupOut:
    return ScannerSetupOut(
        id=str(s.id),
        setup_id=s.setup_id,
        symbol=s.symbol,
        contract=s.contract,
        strategy_key=s.strategy_key,
        strategy_name=s.strategy_name,
        strategy_version=s.strategy_version,
        direction=s.direction,
        detected_at=s.detected_at.isoformat(),
        market_ts=s.market_ts.isoformat(),
        entry_price=float(s.entry_price) if s.entry_price is not None else None,
        stop_price=float(s.stop_price) if s.stop_price is not None else None,
        target_price=float(s.target_price) if s.target_price is not None else None,
        risk_reward=float(s.risk_reward) if s.risk_reward is not None else None,
        status=s.status,
        explanation=s.explanation,
        data_source=s.data_source,
        feed_latency_mode=s.feed_latency_mode,
        forward_run_id=str(s.forward_run_id) if s.forward_run_id else None,
        diagnostics=s.diagnostics or {},
    )


@router.get("/setups", response_model=ScannerSetupList)
async def list_setups(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    symbol: str | None = None,
    status: str | None = None,
    strategy_key: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> ScannerSetupList:
    filters = []
    if symbol:
        filters.append(ScannerSetup.symbol == symbol.upper())
    if status:
        filters.append(ScannerSetup.status == status.upper())
    if strategy_key:
        filters.append(ScannerSetup.strategy_key == strategy_key)
    count_q = select(func.count()).select_from(ScannerSetup)
    if filters:
        count_q = count_q.where(*filters)
    total = await db.scalar(count_q)
    q = select(ScannerSetup)
    if filters:
        q = q.where(*filters)
    rows = (
        await db.execute(q.order_by(desc(ScannerSetup.detected_at)).offset(offset).limit(limit))
    ).scalars().all()
    return ScannerSetupList(
        items=[_row_out(r) for r in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get("/setups/{setup_uuid}", response_model=ScannerSetupOut)
async def get_setup(
    setup_uuid: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScannerSetupOut:
    try:
        uid = UUID(setup_uuid)
    except ValueError:
        uid = None
    row = None
    if uid:
        row = await db.get(ScannerSetup, uid)
    if not row:
        row = (
            await db.execute(select(ScannerSetup).where(ScannerSetup.setup_id == setup_uuid))
        ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Setup not found")
    return _row_out(row)