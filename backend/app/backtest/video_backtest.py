"""Run video-inspired strategies through the shared cost model."""

from __future__ import annotations

from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.dsl import validate_spec
from app.services.market_data.sessions import session_keys_for_bars
from app.backtest.engine import BacktestAssumptions, BacktestResult
from app.backtest.metrics import SimulatedTrade, compute_metrics
from app.backtest.video_execution import run_video_orders
from app.backtest.video_strategies import (
    VideoConfig,
    anchor_bos_orders,
    rollover_suppress_indices,
    session_sweep_orders,
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
    rollover_events = (spec.get("data_context") or {}).get("rollover_events")
    suppress = rollover_suppress_indices(bars, instrument.tick_size, rollover_events)
    if entry_type == "video_liquidity_sweep":
        orders = session_sweep_orders(bars, cfg, session_keys, suppress_indices=suppress)
        warnings = [
            "Video liquidity sweep: prior completed session H/L, optional pivot BOS, fib limit fill next bar+.",
        ]
    elif entry_type == "video_anchor_bos":
        orders = anchor_bos_orders(bars, cfg, suppress_indices=suppress)
        warnings = [
            "Video anchor BOS: confirmed pivots, close break vs prior bar, fib limit fill next bar+.",
        ]
    else:
        raise ValueError(f"Unsupported video entry type: {entry_type}")

    warnings.extend(
        [
            "OHLC-only: limit touch = eligibility, not guaranteed live fill.",
            "Entry bar: no stop/target; ambiguous bar = stop before target; gap exits at open when worse.",
            "One open position at a time per strategy run.",
        ]
    )
    if suppress:
        warnings.append(f"Suppressed signals on {len(suppress)} rollover/gap bar indices.")
    trades, order_stats, exec_analytics = run_video_orders(bars, orders, cfg, instrument)
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
    metrics.update({f"video_{k}": v for k, v in exec_analytics.items() if v is not None})
    metrics["video_order_stats"] = {
        "placed": order_stats.orders_placed,
        "filled": order_stats.orders_filled,
        "expired": order_stats.orders_expired,
        "rejected": order_stats.orders_rejected,
        "cancelled": order_stats.orders_cancelled,
    }
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
    return BacktestResult(trades, metrics, equity_curve, warnings)