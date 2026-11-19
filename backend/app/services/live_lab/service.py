"""Live Strategy Lab orchestration — feed health, candles, forward tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    ForwardTestState,
    LiveFeedConnectionStatus,
    MarketLatencyMode,
    StrategyLifecycle,
)
from app.models.live_lab import ForwardTestRun, LiveFeedStatus
from app.models.strategy import StrategyDefinition
from app.services.live_lab.candle_engine import ingest_market_events
from app.services.live_lab.forward_runner import on_closed_candle, _runner_kind
from app.services.live_lab.ledger import append_ledger_event
from app.services.live_lab.market_data.registry import get_market_data_adapter
from app.services.live_lab.promotion import default_research_state, evaluate_historical_validation, freeze_strategy_version


def ensure_feed_status(session: Session, provider: str) -> LiveFeedStatus:
    row = session.execute(select(LiveFeedStatus).where(LiveFeedStatus.provider == provider)).scalar_one_or_none()
    if row:
        return row
    row = LiveFeedStatus(
        provider=provider,
        connection_status=LiveFeedConnectionStatus.DISCONNECTED,
        latency_mode=MarketLatencyMode.SYNTHETIC,
        incidents=[],
        meta={},
        is_paused=True,
    )
    session.add(row)
    session.flush()
    return row


def start_forward_test(
    session: Session,
    strategy_id: UUID,
    *,
    symbol: str,
    experimental: bool = False,
    actor: str = "user",
) -> ForwardTestRun:
    version = freeze_strategy_version(session, strategy_id)
    if not version:
        raise ValueError("Strategy has no immutable version to freeze")
    spec = dict(version.specification or {})
    spec["instrument_symbol"] = symbol.upper()
    strat = session.get(StrategyDefinition, strategy_id)
    if not strat:
        raise ValueError("Strategy not found")
    ok, reasons, gates = evaluate_historical_validation(session, strategy_id)
    if not ok and not experimental:
        raise ValueError(f"Historical validation failed: {', '.join(reasons)}")
    state = default_research_state(session, strategy_id, experimental=experimental)
    if experimental:
        state = ForwardTestState.FORWARD_TEST_PENDING
    run = ForwardTestRun(
        strategy_id=strategy_id,
        strategy_version_id=version.id,
        symbol=symbol.upper(),
        timeframe=str(spec.get("timeframe") or strat.timeframe or "5m"),
        research_state=ForwardTestState.FORWARD_TEST_PENDING,
        experimental=experimental,
        frozen_specification=spec,
        runner_kind=_runner_kind(spec),
        provider=get_market_data_adapter(session).provider_id,
        latency_mode=MarketLatencyMode.HISTORICAL_REPLAY,
        runner_state={},
    )
    session.add(run)
    session.flush()
    append_ledger_event(
        session,
        run_id=run.id,
        event_type="forward_test_created",
        idempotency_key=f"create:{run.id}",
        payload={"experimental": experimental, "gates": gates, "validation_ok": ok, "actor": actor},
        exchange_ts=None,
    )
    if state == ForwardTestState.HISTORICALLY_VALIDATED or experimental:
        run.research_state = ForwardTestState.FORWARD_TEST_RUNNING
        run.started_at = datetime.now(UTC)
        strat.lifecycle = StrategyLifecycle.PAPER_TRADING
    run.updated_at = datetime.now(UTC)
    return run


def pause_all_forward_tests(session: Session, reason: str) -> int:
    runs = session.execute(
        select(ForwardTestRun).where(ForwardTestRun.research_state == ForwardTestState.FORWARD_TEST_RUNNING)
    ).scalars().all()
    for r in runs:
        r.research_state = ForwardTestState.FORWARD_TEST_PAUSED
        r.pause_reason = reason
        append_ledger_event(
            session,
            run_id=r.id,
            event_type="forward_test_paused",
            idempotency_key=f"pause:{r.id}:{reason[:40]}",
            payload={"reason": reason},
            exchange_ts=None,
        )
    return len(runs)


def tick_live_strategy_lab(session: Session) -> dict:
    adapter = get_market_data_adapter(session)
    feed = ensure_feed_status(session, adapter.provider_id)
    try:
        adapter.connect()
        feed.connection_status = LiveFeedConnectionStatus.CONNECTED
        feed.is_paused = False
        desc_meta = adapter.describe()
        feed.meta = desc_meta
        mode = desc_meta.get("latency_mode") or MarketLatencyMode.SYNTHETIC.value
        feed.latency_mode = MarketLatencyMode(mode)
    except Exception as exc:
        feed.connection_status = LiveFeedConnectionStatus.ERROR
        feed.is_paused = True
        feed.incidents = (feed.incidents or [])[-49:] + [
            {"ts": datetime.now(UTC).isoformat(), "kind": "connect_error", "detail": str(exc)}
        ]
        pause_all_forward_tests(session, f"Feed error: {exc}")
        session.flush()
        return {"ok": False, "error": str(exc)}

    events = adapter.poll_events()
    now = datetime.now(UTC)
    feed.last_heartbeat_at = now
    if events:
        feed.last_event_exchange_ts = events[-1].exchange_ts
        feed.last_event_server_ts = events[-1].server_received_ts

    if feed.latency_mode == MarketLatencyMode.REALTIME:
        stale_cutoff = now - timedelta(seconds=feed.stale_seconds)
        if feed.last_event_exchange_ts and feed.last_event_exchange_ts < stale_cutoff:
            feed.connection_status = LiveFeedConnectionStatus.STALE
            pause_all_forward_tests(session, "Stale realtime feed")
            allow_trading = False
        else:
            allow_trading = True
    elif feed.latency_mode == MarketLatencyMode.DELAYED:
        allow_trading = True
    else:
        allow_trading = True

    completed = ingest_market_events(session, events)
    processed = 0
    runs = session.execute(
        select(ForwardTestRun).where(ForwardTestRun.research_state == ForwardTestState.FORWARD_TEST_RUNNING)
    ).scalars().all()
    for candle in completed:
        decision_ts = candle.server_received_ts or now
        for run in runs:
            on_closed_candle(session, run, candle, decision_ts=decision_ts, allow_trading=allow_trading)
            processed += 1

    feed.updated_at = now
    adapter.disconnect()
    return {
        "ok": True,
        "provider": adapter.provider_id,
        "latency_mode": feed.latency_mode.value,
        "events": len(events),
        "candles_closed": len(completed),
        "runs_touched": len(runs),
        "allow_trading": allow_trading,
        "connection_status": feed.connection_status.value,
    }


def dashboard_summary(session: Session) -> dict:
    feed = session.execute(select(LiveFeedStatus).order_by(LiveFeedStatus.updated_at.desc()).limit(1)).scalar_one_or_none()
    active_runs = session.execute(
        select(func.count()).select_from(ForwardTestRun).where(
            ForwardTestRun.research_state == ForwardTestState.FORWARD_TEST_RUNNING
        )
    ).scalar_one()
    total_pnl = session.execute(select(func.coalesce(func.sum(ForwardTestRun.net_pnl), 0))).scalar_one()
    equity = session.execute(select(func.coalesce(func.sum(ForwardTestRun.equity), 0))).scalar_one()
    runs = session.execute(select(ForwardTestRun).order_by(desc(ForwardTestRun.updated_at)).limit(20)).scalars().all()
    return {
        "feed": {
            "provider": feed.provider if feed else None,
            "connection_status": feed.connection_status.value if feed else "disconnected",
            "latency_mode": feed.latency_mode.value if feed else "synthetic",
            "last_heartbeat_at": feed.last_heartbeat_at.isoformat() if feed and feed.last_heartbeat_at else None,
            "last_event_exchange_ts": feed.last_event_exchange_ts.isoformat()
            if feed and feed.last_event_exchange_ts
            else None,
            "incidents": (feed.incidents if feed else [])[-10:],
            "is_paused": feed.is_paused if feed else True,
        },
        "active_strategy_count": int(active_runs or 0),
        "aggregate_net_pnl": float(total_pnl or 0),
        "aggregate_equity": float(equity or 0),
        "runs": [_run_to_card(r, session) for r in runs],
        "disclaimer": "Simulated forward tests — not broker fills. Live provider not verified without credentials.",
    }


def _run_to_card(run: ForwardTestRun, session: Session) -> dict:
    strat = session.get(StrategyDefinition, run.strategy_id)
    wr = (run.win_count / run.trade_count) if run.trade_count else None
    return {
        "id": str(run.id),
        "strategy_name": strat.name if strat else "—",
        "symbol": run.symbol,
        "timeframe": run.timeframe,
        "version_id": str(run.strategy_version_id),
        "research_state": run.research_state.value,
        "experimental": run.experimental,
        "net_pnl": float(run.net_pnl),
        "trade_count": run.trade_count,
        "max_drawdown": float(run.max_drawdown),
        "win_rate": wr,
        "last_signal_at": run.last_signal_at.isoformat() if run.last_signal_at else None,
        "last_data_exchange_ts": run.last_data_exchange_ts.isoformat() if run.last_data_exchange_ts else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "pause_reason": run.pause_reason,
    }