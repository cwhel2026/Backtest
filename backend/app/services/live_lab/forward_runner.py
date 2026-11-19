"""Forward-test runner — bar-close decisions only, no lookahead."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.backtest.bars import Bar
from app.models.enums import ForwardTestState
from app.models.instrument import Instrument
from app.models.live_lab import ForwardTestRun, LiveCompletedCandle
from app.models.strategy import StrategyDefinition
from app.services.live_lab.candle_engine import load_closed_bars
from app.services.live_lab.ledger import append_ledger_event
from app.services.live_lab.paper_broker import PaperBroker
from app.services.paper_engine import ClosedFill, SlotCursor, advance_slot


VIDEO_ENTRY_TYPES = frozenset(
    {"video_liquidity_sweep", "video_anchor_bos", "berg_tnb_model_v1"}
)


def _runner_kind(spec: dict) -> str:
    entry = (spec.get("entry") or {}).get("type", "")
    if entry in VIDEO_ENTRY_TYPES:
        return "video_incremental"
    return "dsl_bar_close"


def _deserialize_cursor(state: dict) -> SlotCursor:
    pos = None
    if state.get("open_direction"):
        pos = type("OpenTradeProxy", (), state.get("position_proxy"))  # noqa: S305
    return SlotCursor(
        last_bar_ts=datetime.fromisoformat(state["last_bar_ts"]) if state.get("last_bar_ts") else None,
        position=None,
    )


def on_closed_candle(
    session: Session,
    run: ForwardTestRun,
    candle: LiveCompletedCandle,
    *,
    decision_ts: datetime,
    allow_trading: bool,
) -> None:
    """Process one confirmed closed candle for the run's symbol/timeframe."""
    if run.research_state != ForwardTestState.FORWARD_TEST_RUNNING:
        return
    if candle.symbol != run.symbol or candle.timeframe != run.timeframe:
        return
    spec = dict(run.frozen_specification or {})
    from sqlalchemy import select

    inst = session.execute(select(Instrument).where(Instrument.symbol == run.symbol)).scalar_one_or_none()
    if not inst:
        run.pause_reason = f"Unknown instrument {run.symbol}"
        run.research_state = ForwardTestState.FORWARD_TEST_PAUSED
        return

    bar = Bar(ts=candle.ts, open=candle.open, high=candle.high, low=candle.low, close=candle.close, volume=candle.volume)
    run.last_data_exchange_ts = candle.exchange_event_ts or candle.ts
    run.last_decision_ts = decision_ts

    entry_type = (spec.get("entry") or {}).get("type", "")
    if entry_type in VIDEO_ENTRY_TYPES:
        from app.services.live_lab.video_forward import tick_video_forward

        tick_video_forward(session, run, inst, bar, decision_ts, allow_trading=allow_trading)
        return

    bars = load_closed_bars(session, run.symbol, run.timeframe, limit=800)
    if not bars or bars[-1].ts != bar.ts:
        bars.append(bar)
    state = run.runner_state or {}
    cursor = SlotCursor(
        last_bar_ts=datetime.fromisoformat(state["last_bar_ts"]) if state.get("last_bar_ts") else None,
        position=None,
    )
    if state.get("position"):
        p = state["position"]
        from app.services.paper_engine import OpenTrade

        cursor.position = OpenTrade(
            direction=p["direction"],
            qty=p["qty"],
            entry_price=Decimal(p["entry_price"]),
            ref_entry=Decimal(p["ref_entry"]),
            stop=Decimal(p["stop"]),
            target=Decimal(p["target"]),
            entry_ts=datetime.fromisoformat(p["entry_ts"]),
            bars_held=int(p.get("bars_held", 0)),
            initial_risk=Decimal(p.get("initial_risk", "0")),
        )

    cursor, fills = advance_slot(
        spec,
        bars,
        inst,
        cursor,
        allow_entries=allow_trading,
        slip_ticks=1,
    )
    run.runner_state = {
        "last_bar_ts": cursor.last_bar_ts.isoformat() if cursor.last_bar_ts else None,
        "position": (
            {
                "direction": cursor.position.direction,
                "qty": cursor.position.qty,
                "entry_price": str(cursor.position.entry_price),
                "ref_entry": str(cursor.position.ref_entry),
                "stop": str(cursor.position.stop),
                "target": str(cursor.position.target),
                "entry_ts": cursor.position.entry_ts.isoformat(),
                "bars_held": cursor.position.bars_held,
                "initial_risk": str(cursor.position.initial_risk),
            }
            if cursor.position
            else None
        ),
    }
    broker = PaperBroker(session, run.id, inst)
    for fill in fills:
        append_ledger_event(
            session,
            run_id=run.id,
            event_type="trade_closed",
            idempotency_key=f"trade:{run.id}:{fill.entry_ts.isoformat()}:{fill.exit_ts.isoformat()}",
            payload={
                "direction": fill.direction,
                "qty": fill.qty,
                "entry": str(fill.entry_price),
                "exit": str(fill.exit_price),
                "net_pnl": str(fill.net_pnl),
                "reason": fill.exit_reason,
            },
            exchange_ts=fill.exit_ts,
            decision_ts=decision_ts,
        )
        run.net_pnl = Decimal(run.net_pnl) + fill.net_pnl
        run.equity = Decimal(run.equity) + fill.net_pnl
        run.trade_count += 1
        if fill.net_pnl > 0:
            run.win_count += 1
        hw = max(Decimal(run.high_water), Decimal(run.equity))
        run.high_water = hw
        dd = hw - Decimal(run.equity)
        if dd > Decimal(run.max_drawdown):
            run.max_drawdown = dd
        run.last_signal_at = fill.exit_ts
    if cursor.position and allow_trading:
        append_ledger_event(
            session,
            run_id=run.id,
            event_type="signal_entry",
            idempotency_key=f"open:{run.id}:{cursor.position.entry_ts.isoformat()}",
            payload={"direction": cursor.position.direction, "qty": cursor.position.qty},
            exchange_ts=cursor.position.entry_ts,
            decision_ts=decision_ts,
        )
        run.last_signal_at = cursor.position.entry_ts
    run.updated_at = datetime.now(UTC)