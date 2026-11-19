"""Run video-inspired strategies through the shared cost model."""

from __future__ import annotations

from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.dsl import validate_spec
from app.services.market_data.sessions import session_keys_for_bars
from app.backtest.decision_events import DecisionEvent, DecisionEventType, merge_execution_events
from app.backtest.engine import BacktestAssumptions, BacktestResult
from app.backtest.metrics import SimulatedTrade, compute_metrics
from app.backtest.simulation_provenance import build_simulation_provenance
from app.backtest.video_strategies import (
    VideoConfig,
    anchor_bos_orders,
    session_sweep_orders,
    simulate,
    validate_bars,
)
from app.models.instrument import Instrument


def run_video_backtest(
    spec: dict,
    bars: list[Bar],
    instrument: Instrument,
    dataset_timeframe: str,
    assumptions: BacktestAssumptions,
    starting_equity: Decimal = Decimal("100000"),
) -> BacktestResult:
    errors = validate_spec(spec)
    if errors:
        raise ValueError("; ".join(errors))
    validate_bars(bars)
    entry_type = (spec.get("entry") or {}).get("type", "")
    session_keys = session_keys_for_bars(
        bars,
        spec,
        instrument_trading_hours=getattr(instrument, "trading_hours", None) or {},
    )
    cfg = VideoConfig.from_instrument(
        instrument,
        spec,
        slippage_ticks=assumptions.slippage_ticks_per_side,
    )
    if entry_type == "video_liquidity_sweep":
        orders = session_sweep_orders(bars, cfg, session_keys)
        warnings = [
            "Video liquidity sweep: prior completed session H/L, optional pivot BOS, fib limit fill next bar+."
        ]
    elif entry_type == "video_anchor_bos":
        orders = anchor_bos_orders(bars, cfg)
        warnings = [
            "Video anchor BOS: confirmed pivots, close break vs prior bar, fib limit fill next bar+."
        ]
    else:
        raise ValueError(f"Unsupported video entry type: {entry_type}")

    warnings.extend(
        [
            "OHLC-only: stop before target; no intrabar path beyond touch.",
            "One open position at a time per strategy run.",
        ]
    )
    trades = simulate(bars, orders, cfg, instrument)
    simulated = [
        SimulatedTrade(
            t["direction"],
            t["quantity"],
            t["net_pnl"],
            t["gross_pnl"],
            t["commissions"],
            t["slippage"],
            t["mae"],
            t["mfe"],
        )
        for t in trades
    ]
    equity = starting_equity
    equity_curve: list[dict] = []
    if bars:
        equity_curve.append({"ts": bars[0].ts.isoformat(), "equity": float(equity)})
    for t in trades:
        equity += t["net_pnl"]
        equity_curve.append({"ts": t["exit_ts"].isoformat(), "equity": float(equity)})

    metrics = compute_metrics(simulated, starting_equity)
    if int(metrics.get("trade_count") or 0) == 0:
        from app.services.market_data.validate_dataset import backtest_zero_trade_hint, video_strategy_readiness

        readiness = video_strategy_readiness(
            bars,
            symbol=instrument.symbol,
            timeframe=dataset_timeframe,
            instrument_trading_hours=getattr(instrument, "trading_hours", None) or {},
        )
        hint = backtest_zero_trade_hint(0, readiness, "ready")
        if hint:
            warnings.append(f"Zero trades: {hint}")
    events: list[DecisionEvent] = []
    ts_to_index = {b.ts.isoformat(): idx for idx, b in enumerate(bars)}
    for o in orders:
        events.append(
            DecisionEvent(
                ts=bars[o.signal_index].ts,
                bar_index=o.signal_index,
                event_type=DecisionEventType.ORDER_SUBMITTED,
                strategy=entry_type,
                strategy_version="v1",
                setup_id=f"video-{o.signal_index}",
                direction=o.direction,
                explanation=o.reason,
                rule_id=f"video.{entry_type}.signal",
                source="pdf_confirmed",
                levels={"limit": str(o.limit), "stop": str(o.stop), "target": str(o.target)},
                data_available_ts=bars[o.signal_index].ts,
            )
        )
    for i, t in enumerate(trades):
        order_ev = (t.get("meta") or {}).get("order_events") or []
        events = merge_execution_events(
            events,
            order_ev,
            strategy=entry_type,
            setup_id=f"video-trade-{i + 1}",
            bar_index_lookup=ts_to_index,
            include_placed=False,
        )
    dc = spec.get("data_context") or {}
    provenance = build_simulation_provenance(
        spec=spec,
        instrument_symbol=instrument.symbol,
        dataset_version=dc.get("dataset_version"),
        dataset_checksum=dc.get("dataset_checksum"),
        timeframe=dataset_timeframe,
        bar_count=len(bars),
    )
    metrics["decision_event_count"] = len(events)
    return BacktestResult(
        trades,
        metrics,
        equity_curve,
        warnings,
        decision_events=[e.to_dict() for e in events],
        rejected_setups=[],
        simulation_provenance=provenance,
    )