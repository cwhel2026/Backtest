from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.dsl import build_signal_context, signal_at_bar
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.models.enums import AssetClass
from app.models.instrument import Instrument


def _mes() -> Instrument:
    return Instrument(
        symbol="MES",
        name="MES",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        multiplier=Decimal("5"),
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )


def _bars_with_bull_fvg() -> list[Bar]:
    start = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    bars: list[Bar] = []
    p = Decimal("5200")
    for i in range(40):
        ts = start + timedelta(minutes=5 * i)
        if i == 5:
            bars.append(Bar(ts=ts, open=p, high=p + 2, low=p - 1, close=p, volume=100))
            continue
        if i == 7:
            bars.append(Bar(ts=ts, open=p + 6, high=p + 8, low=p + 5, close=p + 7, volume=100))
            continue
        bars.append(
            Bar(ts=ts, open=p, high=p + 1, low=p - Decimal("0.5"), close=p, volume=100),
        )
        p += Decimal("0.1")
    return bars


def test_fvg_spec_validates_and_runs():
    spec = {
        "name": "MES FVG test",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "fair_value_gap",
        "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
        "entry": {"type": "fair_value_gap", "min_gap_ticks": 2, "max_age_bars": 30, "side": "both"},
        "exit": {"stop_ticks": 20, "target_ticks": 24, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    bars = _bars_with_bull_fvg()
    result = run_backtest(spec, bars, _mes(), "5m", BacktestAssumptions())
    assert "trade_count" in result.metrics


def test_liquidity_sweep_signal_path():
    bars = _bars_with_bull_fvg()
    spec = {
        "name": "liq",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "liquidity_sweep",
        "session": {"allowed": ["RTH"]},
        "entry": {"type": "liquidity_sweep", "lookback": 8, "sweep_ticks": 2},
        "exit": {"stop_ticks": 16, "target_ticks": 24, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    keys = ["d"] * len(bars)
    ctx = build_signal_context(spec, bars, keys, instrument_tick=Decimal("0.25"))
    # smoke: no crash across bar indices
    for i in range(10, len(bars) - 2):
        signal_at_bar(spec, bars, i, keys, Decimal("0.25"), ctx)