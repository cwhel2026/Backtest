"""Incremental chronological forward tests for video + Berg strategies."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.backtest.bars import Bar
from app.backtest.video_strategies import VideoConfig
from app.models.instrument import Instrument
from app.models.live_lab import ForwardTestRun
from app.services.live_lab.candle_engine import load_closed_bars
from app.services.live_lab.incremental_executor import ForwardExecutorState, IncrementalVideoForwardEngine
from app.services.live_lab.incremental_signals import discover_berg_orders, discover_video_orders
from app.services.live_lab.ledger import append_ledger_event


def _load_executor_state(run: ForwardTestRun) -> ForwardExecutorState:
    raw = run.runner_state or {}
    if raw.get("version") == 2:
        return ForwardExecutorState(
            version=2,
            last_bar_ts=raw.get("last_bar_ts"),
            bars_count=int(raw.get("bars_count", 0)),
            busy_until=int(raw.get("busy_until", -1)),
            pending=list(raw.get("pending") or []),
            open_position=raw.get("open_position"),
            placed_setup_keys=list(raw.get("placed_setup_keys") or []),
            stats=dict(raw.get("stats") or {}),
        )
    return ForwardExecutorState()


def _save_executor_state(run: ForwardTestRun, eng: IncrementalVideoForwardEngine) -> None:
    st = eng.state
    run.runner_state = {
        "version": 2,
        "last_bar_ts": st.last_bar_ts,
        "bars_count": st.bars_count,
        "busy_until": st.busy_until,
        "pending": st.pending,
        "open_position": st.open_position,
        "placed_setup_keys": st.placed_setup_keys,
        "stats": {
            "orders_placed": eng.stats.orders_placed,
            "orders_filled": eng.stats.orders_filled,
            "orders_expired": eng.stats.orders_expired,
        },
    }


def tick_video_forward(
    session: Session,
    run: ForwardTestRun,
    instrument: Instrument,
    bar: Bar,
    decision_ts: datetime,
    *,
    allow_trading: bool,
) -> None:
    if not allow_trading:
        return
    spec = dict(run.frozen_specification or {})
    entry = (spec.get("entry") or {}).get("type", "")
    cfg = VideoConfig.from_instrument(instrument, spec)
    state = _load_executor_state(run)
    eng = IncrementalVideoForwardEngine(state, cfg, instrument)

    if entry == "berg_tnb_model_v1":
        bars_5m = load_closed_bars(session, run.symbol, "5m", limit=1200)
        if not bars_5m or bars_5m[-1].ts < bar.ts:
            bars_5m.append(bar)
        bars_4h = load_closed_bars(session, run.symbol, "4h", limit=200)
        if len(bars_4h) < 3:
            append_ledger_event(
                session,
                run_id=run.id,
                event_type="rejected_setup",
                idempotency_key=f"berg:no_4h:{bar.ts.isoformat()}",
                payload={"reason": "Berg TNB requires confirmed closed 4H candles", "unresolved": "4h bias sourced from live store"},
                exchange_ts=bar.ts,
                decision_ts=decision_ts,
            )
            return
        bars = bars_5m
    else:
        bars = load_closed_bars(session, run.symbol, run.timeframe, limit=1200)
        if not bars or bars[-1].ts < bar.ts:
            bars.append(bar)

    bar_index = len(bars) - 1
    if state.last_bar_ts == bar.ts.isoformat():
        return

    if entry == "berg_tnb_model_v1":
        new_orders = discover_berg_orders(spec, bars, instrument, at_index=bar_index)
    else:
        new_orders = discover_video_orders(spec, bars, instrument, at_index=bar_index)

    for order in new_orders:
        placed = eng.submit_order(order, bars)
        for ev in placed:
            append_ledger_event(
                session,
                run_id=run.id,
                event_type=ev["type"],
                idempotency_key=f"{ev['type']}:{run.id}:{ev.get('setup_id')}:{bar.ts.isoformat()}",
                payload=ev,
                exchange_ts=bar.ts,
                decision_ts=decision_ts,
            )
            run.last_signal_at = bar.ts

    result = eng.on_bar(bars, bar_index)
    for ev in result.events:
        append_ledger_event(
            session,
            run_id=run.id,
            event_type=ev["type"],
            idempotency_key=f"{ev['type']}:{run.id}:{bar_index}:{ev.get('bar_index', bar_index)}",
            payload=ev,
            exchange_ts=bar.ts,
            decision_ts=decision_ts,
        )

    if result.trade_closed:
        t = result.trade_closed
        key = f"{t['direction']}:{t['entry_ts'].isoformat()}:{t['exit_ts'].isoformat()}"
        append_ledger_event(
            session,
            run_id=run.id,
            event_type="trade_closed",
            idempotency_key=f"incremental:{run.id}:{key}",
            payload={
                "direction": t["direction"],
                "qty": t["quantity"],
                "net_pnl": str(t["net_pnl"]),
                "exit_reason": t["exit_reason"],
                "uncertainties": (t.get("meta") or {}).get("uncertainties", []),
                "incremental": True,
                "entry_type": entry,
            },
            exchange_ts=t["exit_ts"],
            decision_ts=decision_ts,
        )
        pnl = Decimal(str(t["net_pnl"]))
        run.net_pnl = Decimal(run.net_pnl) + pnl
        run.equity = Decimal(run.equity) + pnl
        run.trade_count += 1
        if pnl > 0:
            run.win_count += 1
        hw = max(Decimal(run.high_water), Decimal(run.equity))
        run.high_water = hw
        dd = hw - Decimal(run.equity)
        if dd > Decimal(run.max_drawdown):
            run.max_drawdown = dd
        run.last_signal_at = t["exit_ts"]

    _save_executor_state(run, eng)
    run.last_data_exchange_ts = bar.ts
    run.last_decision_ts = decision_ts
    run.updated_at = datetime.now(UTC)