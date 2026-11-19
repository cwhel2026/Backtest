"""Run Berg TNB v1 through shared execution + metrics."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.berg_tnb.pipeline import BergTnbEngine
from app.backtest.dsl import validate_spec
from app.backtest.engine import BacktestAssumptions, BacktestResult
from app.backtest.metrics import SimulatedTrade, compute_metrics
from app.backtest.video_execution import run_video_orders
from app.backtest.video_strategies import VideoConfig, validate_bars
from app.models.instrument import Instrument


def run_berg_tnb_backtest(
    spec: dict,
    bars: list[Bar],
    instrument: Instrument,
    dataset_timeframe: str,
    assumptions: BacktestAssumptions,
    starting_equity: Decimal = Decimal("100000"),
) -> BacktestResult:
    _ = dataset_timeframe
    errors = validate_spec(spec)
    if errors:
        raise ValueError("; ".join(errors))
    if (spec.get("entry") or {}).get("type") != "berg_tnb_model_v1":
        raise ValueError("entry.type must be berg_tnb_model_v1")
    validate_bars(bars)
    if bars and not _has_4h_history(bars):
        return BacktestResult(
            [],
            compute_metrics([], starting_equity),
            [{"ts": bars[0].ts.isoformat(), "equity": float(starting_equity)}],
            ["Insufficient history for 4H bias — need longer dataset."],
        )

    engine = BergTnbEngine(spec, bars, instrument.tick_size)
    setups, orders = engine.run()
    cfg = VideoConfig.from_instrument(
        instrument,
        spec,
        slippage_ticks=assumptions.slippage_ticks_per_side,
    )
    trades, order_stats, exec_analytics = run_video_orders(bars, orders, cfg, instrument)
    setup_by_order: dict[int, dict] = {}
    for s in setups:
        if s.order_index is not None:
            setup_by_order[s.order_index] = _setup_payload(s)

    for s in setups:
        if s.order_index is not None:
            setup_by_order[s.order_index] = _setup_payload(s)
    for i, t in enumerate(trades):
        meta = t.setdefault("meta", {})
        idx = setups[i].order_index if i < len(setups) else None
        if idx is None and setups:
            idx = setups[0].order_index
        if idx is not None:
            meta["berg_setup"] = setup_by_order.get(idx, {})
            meta["berg_timeline"] = meta["berg_setup"].get("transitions", [])
        meta["strategy"] = "berg_tnb_model_v1"
        meta["session_profile"] = (spec.get("entry") or {}).get("session_profile", "pdf_indices")
        meta["exit_profile"] = (spec.get("exit_meta") or {}).get("profile", "structural_rr")
        meta["execution_assumption"] = (spec.get("entry") or {}).get("execution_scenario", "ohlc_conservative")

    warnings = [
        "Berg TNB v1: PDF not in repo — user-written spec + docs/BERG_TNB_MODEL.md.",
        "Fractals = configurable approximation (Rachel_T unverified).",
        f"Session profile: {(spec.get('entry') or {}).get('session_profile', 'pdf_indices')}.",
        "OHLC limit touch = eligibility, not guaranteed live fill.",
        f"Setups discovered: {len(setups)}; orders: {len(orders)}; trades: {len(trades)}.",
    ]
    simulated = [
        SimulatedTrade(
            t["direction"],
            t["quantity"],
            t["net_pnl"],
            t["gross_pnl"],
            t["commissions"],
            t["slippage"],
            t.get("mae", Decimal(0)),
            t.get("mfe", Decimal(0)),
        )
        for t in trades
    ]
    equity = starting_equity
    curve = [{"ts": bars[0].ts.isoformat(), "equity": float(equity)}] if bars else []
    for t in trades:
        equity += t["net_pnl"]
        curve.append({"ts": t["exit_ts"].isoformat(), "equity": float(equity)})
    metrics = compute_metrics(simulated, starting_equity)
    metrics["berg_setups"] = len(setups)
    metrics["berg_orders"] = len(orders)
    metrics["strategy_id"] = "berg_tnb_model_v1"
    metrics.update({f"video_{k}": v for k, v in exec_analytics.items() if v is not None})
    metrics["execution_engine"] = "video_execution_pr47_compatible"
    metrics["video_order_stats"] = {
        "placed": order_stats.orders_placed,
        "filled": order_stats.orders_filled,
        "expired": order_stats.orders_expired,
    }
    return BacktestResult(trades, metrics, curve, warnings)


def _has_4h_history(bars: list[Bar]) -> bool:
    if len(bars) < 49:
        return False
    span = (bars[-1].ts - bars[0].ts).total_seconds()
    return span >= 4 * 3600


def _setup_payload(setup) -> dict:
    return {
        "setup_id": setup.setup_id,
        "final_state": setup.final_state.value,
        "transitions": [
            {
                "ts": tr.ts.isoformat(),
                "from": tr.from_state.value,
                "to": tr.to_state.value,
                "bar_index": tr.bar_index,
                "reason": tr.reason,
                "evidence": tr.evidence,
            }
            for tr in setup.transitions
        ],
        "bias": asdict(setup.bias) if setup.bias else None,
        "session_level": asdict(setup.session_level) if setup.session_level else None,
        "fakeout": asdict(setup.fakeout) if setup.fakeout else None,
        "bos": asdict(setup.bos) if setup.bos else None,
        "entry_fib": asdict(setup.entry_fib) if setup.entry_fib else None,
    }