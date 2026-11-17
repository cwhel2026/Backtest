"""Backtest engine tests use explicitly synthetic OHLCV — not real market performance."""

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