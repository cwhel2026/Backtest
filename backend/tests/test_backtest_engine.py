"""Backtest engine tests use explicitly synthetic OHLCV — not real market performance."""

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.models.enums import AssetClass
from app.models.instrument import Instrument


def _mes() -> Instrument:
    return Instrument(
        symbol="MES",
        name="Micro E-mini S&P 500",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        multiplier=Decimal("5"),
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )


def _synthetic_rth_bars() -> list[Bar]:
    # Synthetic stair-step series for unit tests only (UTC timestamps aligned to Chicago RTH via engine session keys)
    start = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)  # 08:30 Chicago (DST)
    bars: list[Bar] = []
    price = Decimal("5200")
    for i in range(80):
        ts = start + timedelta(minutes=5 * i)
        drift = Decimal(str(i * 0.1))
        o = price + drift
        c = o + Decimal("0.5")
        bars.append(
            Bar(
                ts=ts,
                open=o,
                high=c + Decimal("1"),
                low=o - Decimal("0.5"),
                close=c,
                volume=1000 + i,
            )
        )
    return bars


def test_backtest_no_lookahead_uses_next_bar_open():
    spec = {
        "name": "test ema",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "trend",
        "session": {"allowed": ["RTH"]},
        "entry": {"type": "ema_crossover", "fast_period": 3, "slow_period": 5},
        "exit": {"stop_ticks": 40, "target_ticks": 40, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    result = run_backtest(spec, _synthetic_rth_bars(), _mes(), "5m", BacktestAssumptions())
    for t in result.trades:
        assert t["entry_ts"] > t["signal_ts"]


def test_invert_flips_trade_direction():
    spec = {
        "name": "test ema",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "trend",
        "session": {"allowed": ["RTH"]},
        "entry": {"type": "ema_crossover", "fast_period": 3, "slow_period": 5},
        "exit": {"stop_ticks": 40, "target_ticks": 40, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    bars = _synthetic_rth_bars()
    inst = _mes()
    original = run_backtest(spec, bars, inst, "5m", BacktestAssumptions())
    inverted = dict(spec)
    inverted["entry"] = {**spec["entry"], "invert": True}
    flipped = run_backtest(inverted, bars, inst, "5m", BacktestAssumptions())
    assert len(original.trades) == len(flipped.trades)
    if original.trades:
        assert original.trades[0]["direction"] != flipped.trades[0]["direction"]


def test_rsi_and_donchian_specs_validate_and_run():
    bars = _synthetic_rth_bars()
    inst = _mes()
    rsi = {
        "name": "rsi",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "rsi_reversion",
        "session": {"allowed": ["RTH"]},
        "entry": {"type": "rsi_reversion", "period": 5, "oversold": 40, "overbought": 60},
        "exit": {"stop_ticks": 20, "target_ticks": 20, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    don = {
        "name": "don",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "donchian_breakout",
        "session": {"allowed": ["RTH"]},
        "entry": {"type": "donchian_breakout", "lookback": 5},
        "exit": {"stop_ticks": 20, "target_ticks": 20, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    r = run_backtest(rsi, bars, inst, "5m", BacktestAssumptions())
    d = run_backtest(don, bars, inst, "5m", BacktestAssumptions())
    assert "trade_count" in r.metrics
    assert "trade_count" in d.metrics


def test_slippage_reported_not_subtracted_twice():
    spec = {
        "name": "test ema",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "trend",
        "session": {"allowed": ["RTH"]},
        "entry": {"type": "ema_crossover", "fast_period": 3, "slow_period": 6},
        "exit": {"stop_ticks": 30, "target_ticks": 30, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
    }
    bars = _synthetic_rth_bars()
    result = run_backtest(spec, bars, _mes(), "5m", BacktestAssumptions(slippage_ticks_per_side=2))
    for t in result.trades:
        gross = Decimal(str(t["gross_pnl"]))
        comm = Decimal(str(t["commissions"]))
        slip = Decimal(str(t["slippage"]))
        net = Decimal(str(t["net_pnl"]))
        assert net == gross - comm
        assert slip >= 0


def test_backtest_reproducible_trade_count():
    spec = {
        "name": "test ema",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "trend",
        "session": {"allowed": ["RTH"]},
        "entry": {"type": "ema_crossover", "fast_period": 3, "slow_period": 6},
        "exit": {"stop_ticks": 30, "target_ticks": 30, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
    }
    bars = _synthetic_rth_bars()
    r1 = run_backtest(spec, bars, _mes(), "5m", BacktestAssumptions(slippage_ticks_per_side=1))
    r2 = run_backtest(spec, bars, _mes(), "5m", BacktestAssumptions(slippage_ticks_per_side=1))
    assert len(r1.trades) == len(r2.trades)
    assert r1.metrics["trade_count"] == r2.metrics["trade_count"]


def _synthetic_orb_sized_bars(num_days: int = 45) -> list[Bar]:
    """~one RTH session per day at 5m (~78 bars/day) to stress the signal loop."""
    start = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    bars: list[Bar] = []
    price = Decimal("18000")
    for day in range(num_days):
        day_start = start + timedelta(days=day)
        for j in range(78):
            ts = day_start + timedelta(minutes=5 * j)
            drift = Decimal(str((day * 78 + j) * 0.02))
            o = price + drift
            c = o + Decimal("0.25")
            bars.append(
                Bar(
                    ts=ts,
                    open=o,
                    high=c + Decimal("2"),
                    low=o - Decimal("1"),
                    close=c,
                    volume=500,
                )
            )
    return bars


def test_orb_backtest_scales_linearly_with_bars():
    """Regression: precomputed ORB map must not revisit every bar on every index."""
    spec = {
        "name": "MNQ ORB",
        "instrument_symbol": "MNQ",
        "timeframe": "5m",
        "category": "opening_range",
        "session": {"allowed": ["RTH"]},
        "entry": {"type": "opening_range_breakout", "range_minutes": 30, "side": "both"},
        "exit": {"stop_ticks": 40, "target_ticks": 80, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
    }
    inst = Instrument(
        symbol="MNQ",
        name="Micro Nasdaq",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("0.50"),
        multiplier=Decimal("2"),
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )
    bars = _synthetic_orb_sized_bars(45)
    t0 = time.monotonic()
    result = run_backtest(spec, bars, inst, "5m", BacktestAssumptions())
    elapsed = time.monotonic() - t0
    assert elapsed < 8.0, f"ORB backtest took {elapsed:.1f}s — likely O(n²) signal path"
    assert "trade_count" in result.metrics