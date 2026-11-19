"""Integration: video strategy entry types route through run_backtest."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.models.enums import AssetClass
from app.models.instrument import Instrument


def _inst(symbol: str) -> Instrument:
    tick = Decimal("0.25") if symbol != "MGC" else Decimal("0.1")
    mult = Decimal("5") if symbol != "MGC" else Decimal("10")
    tick_val = Decimal("1.25") if symbol != "MGC" else Decimal("1")
    return Instrument(
        symbol=symbol,
        name=symbol,
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=tick,
        tick_value=tick_val,
        multiplier=mult,
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )


def _rth_bars(days: int = 3) -> list[Bar]:
    start = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    bars: list[Bar] = []
    price = Decimal("5200")
    for d in range(days):
        for i in range(78):
            ts = start + timedelta(days=d, minutes=5 * i)
            drift = Decimal(str((d * 78 + i) * 0.05))
            o = price + drift
            c = o + Decimal("0.25")
            bars.append(
                Bar(ts=ts, open=o, high=c + Decimal("2"), low=o - Decimal("2"), close=c, volume=1000)
            )
    return bars


def _video_spec(entry_type: str, symbol: str) -> dict:
    return {
        "name": f"{symbol} test {entry_type}",
        "instrument_symbol": symbol,
        "timeframe": "5m",
        "category": entry_type,
        "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
        "entry": {
            "type": entry_type,
            "pivot_left": 2,
            "pivot_right": 2,
            "sweep_ticks": 1,
            "stop_buffer_ticks": 2,
            "fib_ratio": "0.618",
            "reward_risk": "2",
            "order_expire_bars": 8,
            "require_bos_after_sweep": False,
        },
        "exit": {"stop_ticks": 16, "target_ticks": 32},
        "risk": {"dollar_risk_per_trade": 75, "max_contracts": 2},
    }


def test_video_sweep_and_anchor_backtests_complete():
    bars = _rth_bars()
    for sym in ("MNQ", "MES", "MGC"):
        inst = _inst(sym)
        for entry in ("video_liquidity_sweep", "video_anchor_bos"):
            spec = _video_spec(entry, sym)
            result = run_backtest(spec, bars, inst, "5m", BacktestAssumptions())
            assert "trade_count" in result.metrics
            assert isinstance(result.warnings, list)
            for t in result.trades:
                assert t["entry_ts"] >= t["signal_ts"]