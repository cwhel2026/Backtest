"""Run video-inspired strategies through the shared cost model."""

from __future__ import annotations

from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.dsl import session_keys_rth, validate_spec
from app.backtest.engine import BacktestAssumptions, BacktestResult
from app.backtest.metrics import SimulatedTrade, compute_metrics
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
    tz = str((spec.get("session") or {}).get("timezone") or "America/Chicago")
    session_keys = session_keys_rth(bars, tz=tz)
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
    return BacktestResult(trades, metrics, equity_curve, warnings)