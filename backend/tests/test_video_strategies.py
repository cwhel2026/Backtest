"""Deterministic tests for video-inspired strategy module."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.backtest.bars import Bar
from app.backtest.video_strategies import (
    VideoConfig,
    anchor_bos_orders,
    pivots,
    round_tick,
    session_sweep_orders,
    simulate,
    validate_bars,
)


def bar(i: int, o, h, l, c) -> Bar:
    return Bar(
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=i),
        D(str(o)),
        D(str(h)),
        D(str(l)),
        D(str(c)),
        1,
    )


def test_rounding():
    assert round_tick(D("100.13"), D("0.25"), "up") == D("100.25")
    assert round_tick(D("100.13"), D("0.25"), "down") == D("100.00")


def test_pivot_confirmation():
    bars = [bar(i, 10, h, 9, 10) for i, h in enumerate([10, 11, 14, 12, 10, 11])]
    p = pivots(bars, VideoConfig(pivot_left=2, pivot_right=2))
    assert (4, 2, "high", D("14")) in p


def test_next_bar_only_fill():
    from app.models.enums import AssetClass
    from app.models.instrument import Instrument

    bars = [bar(0, 100, 110, 90, 100), bar(1, 100, 101, 99, 100), bar(2, 100, 105, 99, 104)]
    from app.backtest.video_strategies import Order

    o = Order("test", "long", 0, D("100"), D("98"), D("104"), 2, "test")
    inst = Instrument(
        symbol="TST",
        name="Test",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=D("1"),
        tick_value=D("1"),
        multiplier=D("1"),
        trading_hours={},
        default_commission_per_side=D("0"),
    )
    cfg = VideoConfig(
        tick=D("1"),
        multiplier=D("1"),
        slippage_ticks=0,
        commission_side=D("0"),
        risk_dollars=D("100"),
    )
    t = simulate(bars, [o], cfg, inst)
    assert len(t) == 1
    assert t[0]["entry_ts"] == bars[1].ts
    assert t[0]["exit_reason"] == "target"


def test_stop_first_on_ambiguous_bar():
    from app.models.enums import AssetClass
    from app.models.instrument import Instrument
    from app.backtest.video_strategies import Order

    bars = [
        bar(0, 100, 100, 100, 100),
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 106, 94, 100),
    ]
    o = Order("test", "long", 0, D("100"), D("95"), D("105"), 2, "test")
    inst = Instrument(
        symbol="TST",
        name="Test",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=D("1"),
        tick_value=D("1"),
        multiplier=D("1"),
        trading_hours={},
        default_commission_per_side=D("0"),
    )
    cfg = VideoConfig(tick=D("1"), multiplier=D("1"), slippage_ticks=0, commission_side=D("0"))
    t = simulate(bars, [o], cfg, inst)
    assert t[0]["exit_reason"] == "stop"


def test_empty_run_no_crash():
    bars = [bar(i, 100, 101, 99, 100) for i in range(12)]
    validate_bars(bars)
    cfg = VideoConfig()
    assert session_sweep_orders(bars, cfg, ["session"] * 12) == []
    assert anchor_bos_orders(bars, cfg) == []