"""Regression tests aligned to Berg PDF (docs/source/berg_tnb_setup.pdf)."""

from datetime import UTC, datetime
from decimal import Decimal as D

from app.backtest.bars import Bar
from app.backtest.berg_tnb.bias_4h import build_4h_bias_series
from app.backtest.berg_tnb.fib import fakeout_anchor_extremes, fib_fakeout_level
from app.backtest.berg_tnb.fractals import FractalConfig
from app.backtest.berg_tnb.pipeline import _body_close_bos
from app.backtest.berg_tnb.sessions import PDF_INDICES, PDF_FOREX


def _4h(o, h, l, c):
    return Bar(datetime(2026, 1, 1, tzinfo=UTC), D(o), D(h), D(l), D(c), 1)


def test_pdf_indices_ny_open_1430_gmt():
    assert PDF_INDICES.new_york_open_gmt.hour == 14
    assert PDF_INDICES.new_york_open_gmt.minute == 30


def test_pdf_forex_ny_open_1300_gmt():
    assert PDF_FOREX.new_york_open_gmt.hour == 13


def test_wick_through_high_is_not_bos_body_rule():
    b = _4h(99, 105, 98, 99.5)
    assert not _body_close_bos(b, D(100), "bullish")
    b2 = _4h(99, 105, 98, 101)
    assert _body_close_bos(b2, D(100), "bullish")


def test_fakeout_bullish_orientation_0079_near_high():
    level = fib_fakeout_level(D("110"), D("100"), "bullish", D("0.079"))
    assert level == D("110") - D("10") * D("0.079")


def test_fakeout_bearish_orientation_0079_near_low():
    level = fib_fakeout_level(D("110"), D("100"), "bearish", D("0.079"))
    assert level == D("100") + D("10") * D("0.079")


def test_fakeout_anchors_include_sweep_extremes():
    bars = [
        Bar(datetime(2026, 1, 1, tzinfo=UTC), D(1), D(5), D(1), D(4), 1),
        Bar(datetime(2026, 1, 1, 1, tzinfo=UTC), D(4), D(12), D(3), D(10), 1),
    ]
    hi, lo = fakeout_anchor_extremes(bars, session_high=D(5), session_low=D(1), from_index=0, to_index=1)
    assert hi == D(12)
    assert lo == D(1)


def test_4h_bias_undefined_without_body_close():
    bars = [_4h(100, 100, 99, 99) for _ in range(6)]
    bars[4] = _4h(100, 105, 99, 99.5)
    series = build_4h_bias_series(bars, FractalConfig(1, 1))
    assert series[4].direction in (None, series[3].direction)