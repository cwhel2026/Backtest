"""Upsert scanner rows from incremental detections and forward-test ledger events."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.video_strategies import Order, effective_order_prices
from app.models.enums import ScannerSetupStatus
from app.models.live_lab import ForwardTestRun
from app.models.scanner import ScannerSetup
from app.models.strategy import StrategyDefinition


def deterministic_setup_id(*parts: str) -> str:
    raw = "|".join(p for p in parts if p)
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


def _direction_label(direction: str) -> str:
    return "buy" if direction == "long" else "sell"


def _risk_reward(limit: Decimal, stop: Decimal, target: Decimal) -> Decimal | None:
    risk = abs(limit - stop)
    if risk <= 0:
        return None
    reward = abs(target - limit)
    return (reward / risk).quantize(Decimal("0.0001"))


def upsert_order_setup(
    session: Session,
    *,
    order: Order,
    symbol: str,
    strategy_key: str,
    strategy_name: str,
    strategy_version: str,
    market_ts: datetime,
    status: ScannerSetupStatus,
    explanation: str | None,
    forward_run_id: UUID | None,
    data_source: str | None,
    feed_latency_mode: str | None,
    contract: str | None = None,
    diagnostics: dict | None = None,
) -> ScannerSetup:
    limit, stop, target = effective_order_prices(order, order.signal_index)
    sid = deterministic_setup_id(
        strategy_key,
        symbol,
        order.setup_id or "",
        str(order.signal_index),
        str(limit),
        order.direction,
        market_ts.isoformat(),
    )
    now = datetime.now(UTC)
    row = session.execute(select(ScannerSetup).where(ScannerSetup.setup_id == sid)).scalar_one_or_none()
    if not row:
        row = ScannerSetup(
            setup_id=sid,
            symbol=symbol.upper(),
            contract=contract,
            strategy_key=strategy_key,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            direction=_direction_label(order.direction),
            detected_at=now,
            market_ts=market_ts,
            entry_price=limit,
            stop_price=stop,
            target_price=target,
            risk_reward=_risk_reward(limit, stop, target),
            status=status.value,
            explanation=explanation or order.reason,
            data_source=data_source,
            feed_latency_mode=feed_latency_mode,
            forward_run_id=forward_run_id,
            diagnostics=diagnostics or {"uncertainties": [], "source": "incremental_engine"},
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.status = status.value
        row.entry_price = limit
        row.stop_price = stop
        row.target_price = target
        row.risk_reward = _risk_reward(limit, stop, target)
        row.explanation = explanation or row.explanation
        row.updated_at = now
        if diagnostics:
            merged = dict(row.diagnostics or {})
            merged.update(diagnostics)
            row.diagnostics = merged
    return row


def upsert_rejected_candidate(
    session: Session,
    *,
    symbol: str,
    strategy_key: str,
    strategy_name: str,
    strategy_version: str,
    market_ts: datetime,
    reason: str,
    forward_run_id: UUID | None,
    data_source: str | None,
    feed_latency_mode: str | None,
    diagnostics: dict | None = None,
) -> ScannerSetup:
    sid = deterministic_setup_id(strategy_key, symbol, "rejected", market_ts.isoformat(), reason[:80])
    now = datetime.now(UTC)
    row = session.execute(select(ScannerSetup).where(ScannerSetup.setup_id == sid)).scalar_one_or_none()
    if row:
        return row
    row = ScannerSetup(
        setup_id=sid,
        symbol=symbol.upper(),
        contract=None,
        strategy_key=strategy_key,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        direction="—",
        detected_at=now,
        market_ts=market_ts,
        entry_price=None,
        stop_price=None,
        target_price=None,
        risk_reward=None,
        status=ScannerSetupStatus.INVALIDATED.value,
        explanation=reason,
        data_source=data_source,
        feed_latency_mode=feed_latency_mode,
        forward_run_id=forward_run_id,
        diagnostics={**(diagnostics or {}), "rejected_candidate": True},
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    return row


def update_setup_status_by_key(session: Session, setup_key: str | None, status: ScannerSetupStatus) -> None:
    if not setup_key:
        return
    rows = session.execute(select(ScannerSetup).where(ScannerSetup.diagnostics["order_key"].astext == setup_key)).scalars().all()
    for row in rows:
        row.status = status.value
        row.updated_at = datetime.now(UTC)


def sync_from_forward_ledger(
    session: Session,
    run: ForwardTestRun,
    event_type: str,
    payload: dict,
    exchange_ts: datetime | None,
) -> None:
    strat = session.get(StrategyDefinition, run.strategy_id)
    spec = dict(run.frozen_specification or {})
    entry = (spec.get("entry") or {}).get("type", "")
    strategy_key = {
        "berg_tnb_model_v1": "berg_tnb",
        "video_liquidity_sweep": "liquidity_sweep",
        "video_anchor_bos": "anchor_bos",
    }.get(entry, entry or "unknown")
    strategy_name = strat.name if strat else strategy_key.replace("_", " ").title()
    strategy_version = entry or "unknown"
    market_ts = exchange_ts or datetime.now(UTC)

    if event_type == "rejected_setup":
        upsert_rejected_candidate(
            session,
            symbol=run.symbol,
            strategy_key=strategy_key,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            market_ts=market_ts,
            reason=str(payload.get("reason") or "Setup rejected"),
            forward_run_id=run.id,
            data_source=run.provider,
            feed_latency_mode=run.latency_mode.value if run.latency_mode else None,
            diagnostics=payload,
        )
        return

    setup_key = payload.get("setup_id")
    if event_type == "order_placed":
        diag = {"order_key": setup_key, "ledger": payload}
        existing = session.execute(
            select(ScannerSetup).where(ScannerSetup.diagnostics["order_key"].astext == setup_key)
        ).scalar_one_or_none()
        if existing:
            existing.status = ScannerSetupStatus.PENDING_ENTRY.value
            existing.forward_run_id = run.id
            existing.updated_at = datetime.now(UTC)
            return
        # Forward path may not have full Order in payload — store minimal row
        sid = deterministic_setup_id(strategy_key, run.symbol, setup_key or "", market_ts.isoformat())
        now = datetime.now(UTC)
        limit = Decimal(str(payload["limit"])) if payload.get("limit") else None
        row = ScannerSetup(
            setup_id=sid,
            symbol=run.symbol.upper(),
            contract=None,
            strategy_key=strategy_key,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            direction="buy",
            detected_at=now,
            market_ts=market_ts,
            entry_price=limit,
            stop_price=None,
            target_price=None,
            risk_reward=None,
            status=ScannerSetupStatus.PENDING_ENTRY.value,
            explanation="Paper order placed on closed bar",
            data_source=run.provider,
            feed_latency_mode=run.latency_mode.value if run.latency_mode else None,
            forward_run_id=run.id,
            diagnostics=diag,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        return

    status_map = {
        "order_rejected": ScannerSetupStatus.INVALIDATED,
        "order_cancelled": ScannerSetupStatus.CANCELLED,
        "order_expired": ScannerSetupStatus.EXPIRED,
    }
    if event_type in status_map:
        rows = session.execute(
            select(ScannerSetup).where(
                ScannerSetup.forward_run_id == run.id,
                ScannerSetup.diagnostics["order_key"].astext == setup_key,
            )
        ).scalars().all()
        if not rows and setup_key:
            rows = session.execute(
                select(ScannerSetup).where(ScannerSetup.diagnostics["order_key"].astext == setup_key)
            ).scalars().all()
        for row in rows:
            row.status = status_map[event_type].value
            row.updated_at = datetime.now(UTC)
        return

    if event_type == "trade_closed":
        reason = str(payload.get("exit_reason") or "")
        st = ScannerSetupStatus.FILLED_PAPER
        if reason in ("take_profit", "target", "tp"):
            st = ScannerSetupStatus.TP_HIT
        elif reason in ("stop_loss", "stop", "sl"):
            st = ScannerSetupStatus.SL_HIT
        rows = session.execute(
            select(ScannerSetup)
            .where(ScannerSetup.forward_run_id == run.id)
            .order_by(ScannerSetup.detected_at.desc())
            .limit(5)
        ).scalars().all()
        for row in rows:
            if row.status in (ScannerSetupStatus.PENDING_ENTRY.value, ScannerSetupStatus.FILLED_PAPER.value):
                row.status = st.value
                row.updated_at = datetime.now(UTC)
                break