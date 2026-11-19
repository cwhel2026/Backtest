"""Incremental video/Berg forward tests — bar-close only, experimental label required."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.backtest.bars import Bar
from app.backtest.engine import BacktestAssumptions
from app.backtest.video_backtest import run_video_backtest
from app.models.instrument import Instrument
from app.models.live_lab import ForwardTestRun
from app.services.live_lab.candle_engine import load_closed_bars
from app.services.live_lab.ledger import append_ledger_event


def tick_video_forward(
    session: Session,
    run: ForwardTestRun,
    instrument: Instrument,
    bar: Bar,
    decision_ts: datetime,
    *,
    allow_trading: bool,
) -> None:
    """Reconcile new closed trade(s) using chronological video backtest on available history.

    Trades are only committed when their exit timestamp equals the current closed bar (no future fills).
    committed_trade_keys prevents duplicate ledger writes across ticks.
    """
    if not allow_trading:
        return
    spec = dict(run.frozen_specification or {})
    entry = (spec.get("entry") or {}).get("type", "")
    if entry == "berg_tnb_model_v1":
        from app.backtest.berg_tnb.backtest import run_berg_tnb_backtest

        bars_5m = load_closed_bars(session, run.symbol, "5m", limit=600)
        if not bars_5m or bars_5m[-1].ts < bar.ts:
            bars_5m.append(bar)
        bars_4h = load_closed_bars(session, run.symbol, "4h", limit=200)
        if len(bars_4h) < 3:
            append_ledger_event(
                session,
                run_id=run.id,
                event_type="rejected_setup",
                idempotency_key=f"berg:no_4h:{bar.ts.isoformat()}",
                payload={"reason": "Berg TNB requires confirmed closed 4H bias candles in live store"},
                exchange_ts=bar.ts,
                decision_ts=decision_ts,
            )
            return
        result = run_berg_tnb_backtest(
            spec,
            bars_5m,
            instrument,
            dataset_timeframe=run.timeframe,
            assumptions=BacktestAssumptions(),
        )
        trades = result.trades or []
    else:
        bars = load_closed_bars(session, run.symbol, run.timeframe, limit=600)
        if not bars or bars[-1].ts < bar.ts:
            bars.append(bar)
        result = run_video_backtest(
            spec,
            bars,
            instrument,
            dataset_timeframe=run.timeframe,
            assumptions=BacktestAssumptions(),
        )
        trades = result.trades or []

    state = run.runner_state or {}
    seen = set(state.get("committed_trade_keys") or [])
    new_keys: list[str] = []
    for t in trades:
        exit_ts = t.get("exit_ts")
        entry_ts = t.get("entry_ts")
        if exit_ts is None or entry_ts is None:
            continue
        if exit_ts != bar.ts:
            continue
        key = f"{t.get('direction')}:{entry_ts.isoformat()}:{exit_ts.isoformat()}"
        if key in seen:
            continue
        pnl = Decimal(str(t.get("net_pnl", 0)))
        append_ledger_event(
            session,
            run_id=run.id,
            event_type="trade_closed",
            idempotency_key=f"video:{run.id}:{key}",
            payload={
                "direction": t.get("direction"),
                "net_pnl": str(pnl),
                "experimental": run.experimental,
                "entry_type": entry,
            },
            exchange_ts=bar.ts,
            decision_ts=decision_ts,
        )
        run.net_pnl = Decimal(run.net_pnl) + pnl
        run.equity = Decimal(run.equity) + pnl
        run.trade_count += 1
        if pnl > 0:
            run.win_count += 1
        seen.add(key)
        new_keys.append(key)
        run.last_signal_at = bar.ts
    state["committed_trade_keys"] = list(seen)
    run.runner_state = state
    run.updated_at = datetime.now(UTC)