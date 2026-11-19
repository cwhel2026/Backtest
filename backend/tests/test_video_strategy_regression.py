"""Deterministic video strategy scenarios with known outcomes."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.backtest.bars import Bar
from app.backtest.video_execution import run_video_orders
from app.backtest.video_strategies import (
    Order,
    VideoConfig,
    anchor_bos_orders,
    order_from_impulse,
    pivots,
    rollover_suppress_indices,
    session_sweep_orders,
)
from app.models.enums import AssetClass
from app.models.instrument import Instrument


def _mes() -> Instrument:
    return Instrument(
        symbol="MES",
        name="MES",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=D("0.25"),
        tick_value=D("1.25"),
        multiplier=D("5"),
        trading_hours={},
        default_commission_per_side=D("0.62"),
    )


def b(i: int, o, h, l, c) -> Bar:
    return Bar(
        datetime(2026, 1, 5, 14, 0, tzinfo=UTC) + timedelta(minutes=5 * i),
        D(str(o)),
        D(str(h)),
        D(str(l)),
        D(str(c)),
        100,
    )


def _cfg(**kw) -> VideoConfig:
    base = dict(
        tick=D("0.25"),
        multiplier=D("5"),
        commission_side=D("0"),
        slippage_ticks=0,
        risk_dollars=D("1000"),
        max_contracts=10,
        expiry_bars=5,
    )
    base.update(kw)
    return VideoConfig(**base)


def test_long_limit_fills_and_hits_target():
    bars = [b(i, 100, 100.5, 99.5, 100) for i in range(4)]
    bars[2] = b(2, 100, 101, 99, 100.5)
    bars[3] = b(3, 100.5, 104, 100, 103)
    o = Order("t", "long", 0, D("100"), D("98"), D("104"), 3, "test")
    trades, stats, _ = run_video_orders(bars, [o], _cfg(), _mes())
    assert stats.orders_filled == 1
    assert trades[0]["exit_reason"] == "target"
    assert trades[0]["entry_ts"] == bars[1].ts
    assert trades[0]["quantity"] >= 1
    assert trades[0]["net_pnl"] > 0


def test_short_stop_out_with_exact_prices():
    bars = [
        b(0, 100, 100, 100, 100),
        b(1, 100, 101, 99, 100),
        b(2, 100, 103, 99, 102),
        b(3, 102, 106, 101, 105),
    ]
    o = Order("t", "short", 0, D("100"), D("105"), D("90"), 3, "test")
    trades, _, _ = run_video_orders(bars, [o], _cfg(), _mes())
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "stop"
    assert trades[0]["exit_price"] == D("105")


def test_limit_never_fills_expires():
    bars = [b(i, 200, 201, 199, 200) for i in range(6)]
    o = Order("t", "long", 0, D("100"), D("95"), D("110"), 3, "test")
    trades, stats, analytics = run_video_orders(bars, [o], _cfg(), _mes())
    assert not trades
    assert stats.orders_expired == 1
    assert analytics["entry_fill_rate"] == 0.0


def test_rejected_invalid_bracket():
    o = Order("t", "long", 0, D("100"), D("105"), D("110"), 2, "bad")
    trades, stats, _ = run_video_orders(bars=[b(0, 1, 1, 1, 1), b(1, 1, 1, 1, 1)], orders=[o], cfg=_cfg(), instrument=_mes())
    assert stats.orders_rejected == 1
    assert not trades


def test_fib_0618_vs_0595_changes_limit():
    low, high = D("100"), D("110")
    cfg618 = _cfg(fib_retracement=D("0.618"))
    cfg595 = _cfg(fib_retracement=D("0.595"))
    o618 = order_from_impulse("t", "long", 0, low, high, cfg618, "x")
    o595 = order_from_impulse("t", "long", 0, low, high, cfg595, "x")
    assert o618 and o595
    assert o595.limit > o618.limit


def test_anchor_rejects_unconfirmed_pivot():
    bars = [b(i, 10, 10 + i * 0.25, 9.5, 10) for i in range(20)]
    orders = anchor_bos_orders(bars, _cfg(pivot_left=2, pivot_right=2))
    assert orders == []


def test_session_boundary_uses_prior_session_only():
    keys = ["s1"] * 5 + ["s2"] * 8
    bars = [
        b(0, 10, 11, 9, 10),
        b(1, 10, 12, 9, 11),
        b(2, 11, 12, 10, 11),
        b(3, 11, 13, 10, 12),
        b(4, 12, 13, 11, 12),
        b(5, 12, 14, 11, 13),
        b(6, 13, 15, 12, 14),
        b(7, 14, 16, 13, 15),
        b(8, 15, 17, 14, 16),
        b(9, 16, 18, 15, 17),
        b(10, 17, 19, 16, 18),
        b(11, 18, 20, 17, 19),
        b(12, 19, 21, 18, 20),
    ]
    cfg = _cfg(require_bos_after_sweep=False, sweep_ticks=0)
    orders = session_sweep_orders(bars, cfg, keys)
    assert all(o.signal_index >= 5 for o in orders)


def test_rollover_bar_suppresses_signal_index():
    bars = [
        b(0, 100, 101, 99, 100),
        b(1, 100, 101, 99, 100),
        b(2, 500, 501, 499, 500),
        b(3, 500, 501, 499, 500),
    ]
    suppress = rollover_suppress_indices(bars, D("0.25"))
    assert 2 in suppress
    assert 1 in suppress


def test_pivot_confirmation_lags_signal():
    bars = [b(i, 10, 10.5, 9.5, 10) for i in range(12)]
    bars[5] = b(5, 10, 14, 9, 13)
    p = pivots(bars, _cfg(pivot_left=2, pivot_right=2))
    highs = [x for x in p if x[2] == "high"]
    assert highs[0][0] >= 5 + 2


def test_ambiguous_bar_stop_before_target():
    bars = [
        b(0, 100, 100, 100, 100),
        b(1, 100, 100, 99, 99.75),
        b(2, 99.5, 106, 94, 100),
    ]
    o = Order("t", "long", 0, D("100"), D("95"), D("105"), 2, "test")
    trades, _, _ = run_video_orders(bars, [o], _cfg(), _mes())
    assert trades[0]["exit_reason"].startswith("stop")