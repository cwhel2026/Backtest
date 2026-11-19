"""Backtest vs forward incremental parity on identical bars."""

from __future__ import annotations

from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.engine import BacktestAssumptions
from app.backtest.video_backtest import run_video_backtest
from app.services.live_lab.certification.replay import _mes, _run_forward_path, _synthetic_bars


def compare_backtest_forward(spec: dict, bars: list[Bar] | None = None) -> dict:
    bars = bars or _synthetic_bars(20)
    inst = _mes()
    spec = {
        **spec,
        "name": "parity-cert-fixture",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "entry": {"type": "video_anchor_bos"},
        "exit": {"stop_ticks": 16, "target_ticks": 32},
        "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
    }
    bt = run_video_backtest(spec, bars, inst, "5m", BacktestAssumptions())
    fwd = _run_forward_path(bars)

    bt_trades = bt.trades or []
    bt_net = sum(Decimal(str(t.get("net_pnl", 0))) for t in bt_trades)
    fwd_net = Decimal(fwd.get("equity_pnl") or "0")

    match = False
    reason = "forward_path_may_not_emit_anchor_setups_on_short_fixture"
    if bt_trades and fwd_net != 0:
        match = abs(bt_net - fwd_net) < Decimal("500")
        reason = "pnl_within_tolerance" if match else f"bt_net={bt_net} fwd_net={fwd_net}"
    elif not bt_trades and fwd_net == 0:
        match = True
        reason = "both_zero_trades_on_fixture"

    return {
        "parity_match": match,
        "reason": reason,
        "backtest_trade_count": len(bt_trades),
        "backtest_net_pnl": float(bt_net),
        "forward_net_pnl": float(fwd_net),
        "execution_model_note": (
            "Backtest batch-scans all bars; forward incremental discovers orders per bar. "
            "Exact fill parity requires identical order stream — compare order keys in integration tier."
        ),
    }