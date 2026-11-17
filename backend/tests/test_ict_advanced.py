from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.dsl import validate_spec
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.backtest.ict import range_position, session_dealing_ranges
from app.models.enums import AssetClass
from app.models.instrument import Instrument


def _bars(n: int = 60) -> list[Bar]:
    start = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    p = Decimal("5000")
    out: list[Bar] = []
    for i in range(n):
        ts = start + timedelta(minutes=5 * i)
        c = p + Decimal(str(i * 0.05))
        out.append(Bar(ts=ts, open=c, high=c + 2, low=c - 1, close=c, volume=200))
    return out


def test_premium_discount_position():
    keys = ["2024-06-03"] * 60
    sr = session_dealing_ranges(_bars(), keys)["2024-06-03"]
    assert range_position(sr.low, sr) == Decimal(0)
    assert range_position(sr.high, sr) == Decimal(1)


def test_new_entry_types_validate_and_run():
    inst = Instrument(
        symbol="MES",
        name="MES",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        multiplier=Decimal("5"),
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )
    bars = _bars()
    specs = [
        {
            "name": "ob",
            "instrument_symbol": "MES",
            "timeframe": "5m",
            "category": "order_block",
            "session": {"allowed": ["RTH"]},
            "entry": {"type": "order_block_retest", "displacement_ticks": 8, "max_age_bars": 40, "side": "both"},
            "exit": {"stop_ticks": 16, "target_ticks": 24, "session_end_flatten": True},
            "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
        },
        {
            "name": "pd",
            "instrument_symbol": "MES",
            "timeframe": "5m",
            "category": "premium_discount",
            "session": {"allowed": ["RTH"]},
            "entry": {"type": "premium_discount", "discount_max": 0.4, "premium_min": 0.6, "zone": "both"},
            "exit": {"stop_ticks": 16, "target_ticks": 24, "session_end_flatten": True},
            "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
        },
        {
            "name": "mtf",
            "instrument_symbol": "MES",
            "timeframe": "5m",
            "category": "mtf_pullback",
            "session": {"allowed": ["RTH"]},
            "entry": {"type": "mtf_ema_pullback", "htf": "15m", "fast_period": 8, "slow_period": 21},
            "exit": {"stop_ticks": 16, "target_ticks": 24, "session_end_flatten": True},
            "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
        },
    ]
    for spec in specs:
        assert not validate_spec(spec)
        r = run_backtest(spec, bars, inst, "5m", BacktestAssumptions())
        assert "trade_count" in r.metrics