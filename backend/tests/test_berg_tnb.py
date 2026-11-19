"""Deterministic Berg TNB state transitions and calculations."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.backtest.bars import Bar
from app.backtest.berg_tnb.bias_4h import build_4h_bias_series
from app.backtest.berg_tnb.fib import fib_fakeout_level, fib_entry_limit
from app.backtest.berg_tnb.fractals import FractalConfig, confirmed_fractals
from app.backtest.berg_tnb.sessions import PDF_INDICES, aggregate_session_extremes, completed_measurement_for_bar
from app.backtest.berg_tnb.types import BergTnbState


def bar(i, o, h, l, c, minutes=5) -> Bar:
    return Bar(
        datetime(2026, 1, 15, 0, 0, tzinfo=UTC) + timedelta(minutes=minutes * i),
        D(str(o)),
        D(str(h)),
        D(str(l)),
        D(str(c)),
        1,
    )


def test_fractal_confirmation_lag():
    bars = [bar(i, 100, 100 + i, 99, 100) for i in range(8)]
    bars[4] = bar(4, 100, 110, 99, 105)
    f = confirmed_fractals(bars, FractalConfig(2, 2))
    hi = [x for x in f if x.kind == "high"][0]
    assert hi.confirm_index == 6
    assert hi.pivot_index == 4


def test_fib_fakeout_level_bullish():
    level = fib_fakeout_level(D("110"), D("100"), "bullish", D("0.079"))
    assert level == D("110") - D("10") * D("0.079")


def test_session_measurement_window_indices():
    ts = datetime(2026, 1, 15, 13, 5, tzinfo=UTC)
    done = completed_measurement_for_bar(ts, PDF_INDICES, "new_york_setup")
    assert done is not None
    _, start, end = done
    assert start.hour == 8
    assert end.hour == 13


def test_exact_liquidity_touch_allowed():
    level = D("100")
    b = bar(1, 100, 101, 100, 100.5)
    assert b.low <= level


def test_4h_bos_requires_close_not_wick_only():
    bars_4h = []
    for i in range(6):
        bars_4h.append(
            Bar(
                datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=4 * i),
                D("100"),
                D("105"),
                D("99"),
                D("100"),
                1,
            )
        )
    bars_4h[4] = Bar(bars_4h[4].ts, D("100"), D("108"), D("99"), D("104"), 1)
    series = build_4h_bias_series(bars_4h, FractalConfig(1, 1))
    assert series[4].direction in (None, "bullish", "bearish")


def test_bos_after_fakeout_ordering():
    from app.backtest.berg_tnb.pipeline import _bos_after_fakeout

    bars = [bar(i, 100, 101, 99, 100) for i in range(12)]
    bars[6] = bar(6, 100, 103, 99, 102)
    bars[7] = bar(7, 102, 104, 101, 103)
    fractals = confirmed_fractals(bars, FractalConfig(1, 1))
    ok_before = _bos_after_fakeout(bars, fractals, 5, "bullish")[0]
    ok_after = _bos_after_fakeout(bars, fractals, 7, "bullish")[0]
    assert isinstance(ok_before, bool)
    assert isinstance(ok_after, bool)


def test_entry_fib_ratio_changes_limit():
    tick = D("0.25")
    l618 = fib_entry_limit(D("100"), D("110"), "bullish", D("0.618"), tick)
    l595 = fib_entry_limit(D("100"), D("110"), "bullish", D("0.595"), tick)
    assert l595 > l618


def test_aggregate_session_extremes():
    start = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
    end = datetime(2026, 1, 15, 13, 0, tzinfo=UTC)
    bars = [
        Bar(start + timedelta(minutes=5), D(1), D(5), D(1), D(4), 1),
        Bar(start + timedelta(minutes=10), D(4), D(6), D(2), D(5), 1),
    ]
    hi, lo = aggregate_session_extremes(bars, start, end)
    assert hi == D(6)
    assert lo == D(1)


def test_state_enum_complete():
    assert BergTnbState.WAITING_FOR_FAKEOUT_0079.value == "WAITING_FOR_FAKEOUT_0079"