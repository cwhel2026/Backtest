from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.models.enums import AssetClass
from app.models.instrument import Instrument
from app.services.paper_engine import OpenTrade, SlotCursor, advance_slot, apply_prop_rules


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


def _bar(i: int, o: str, h: str, l: str, c: str) -> Bar:
    return Bar(
        ts=datetime(2024, 6, 3, 13, 30, tzinfo=UTC) + timedelta(minutes=5 * i),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(l),
        close=Decimal(c),
        volume=100,
    )


def test_first_tick_does_not_replay_history():
    bars = [_bar(i, "5200", "5201", "5199", "5200.5") for i in range(10)]
    spec = {
        "entry": {"type": "ema_crossover", "fast_period": 3, "slow_period": 5},
        "exit": {"stop_ticks": 8, "target_ticks": 16},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    cursor, fills = advance_slot(spec, bars, _mes(), SlotCursor(None, None), allow_entries=True)
    assert fills == []
    assert cursor.position is None
    assert cursor.last_bar_ts == bars[-1].ts


def test_open_long_stops_out_on_new_bar():
    bars = [
        _bar(0, "5200", "5201", "5199", "5200"),
        _bar(1, "5200", "5201", "5180", "5185"),
    ]
    pos = OpenTrade("long", 1, Decimal("5200"), Decimal("5190"), Decimal("5220"), bars[0].ts)
    cursor, fills = advance_slot(
        {"entry": {"type": "ema_crossover"}, "exit": {}, "risk": {}},
        bars,
        _mes(),
        SlotCursor(bars[0].ts, pos),
        allow_entries=False,
    )
    assert len(fills) == 1
    assert fills[0].exit_reason == "stop_loss"
    assert cursor.position is None


def test_trailing_drawdown_breaches():
    hw, status = apply_prop_rules(
        equity=Decimal("96000"),
        high_water=Decimal("100000"),
        day_start=Decimal("100000"),
        daily_loss_limit=Decimal("5000"),
        trailing_drawdown=Decimal("3000"),
        profit_target=Decimal("6000"),
        starting_equity=Decimal("100000"),
    )
    assert status == "breached"
    assert hw == Decimal("100000")
