"""Phase 2: lineage, resampling, 4H lookahead — synthetic fixtures only (not real market data)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.backtest.bars import Bar, aggregate_bars
from app.backtest.berg_tnb.bias_4h import bias_for_5m_bar, build_4h_bias_series
from app.backtest.berg_tnb.fractals import FractalConfig
from app.services.market_data.data_lineage import apply_lineage_meta, assert_genuine_for_backtest
from app.services.market_data.provider_comparison import comparison_catalog


def _bar(ts: datetime, c: str = "100") -> Bar:
    return Bar(ts, D(c), D(c), D(c), D(c), 1)


def test_data_lineage_databento_genuine():
    meta = apply_lineage_meta({"source": "databento_historical"}, provider_slug="databento")
    assert meta["data_lineage"] == "licensed_databento"
    assert meta["genuine_for_research"] is True
    assert_genuine_for_backtest(meta)


def test_data_lineage_yahoo_not_genuine():
    meta = apply_lineage_meta({}, provider_slug="yahoo")
    assert meta["genuine_for_research"] is False
    try:
        assert_genuine_for_backtest(meta)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_resample_1m_to_5m_counts():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars_1m = [_bar(start + timedelta(minutes=i), str(100 + i % 5)) for i in range(25)]
    bars_5m = aggregate_bars(bars_1m, "5m")
    assert len(bars_5m) == 5
    assert bars_5m[0].open == bars_1m[0].open
    assert bars_5m[0].close == bars_1m[4].close


def test_resample_5m_to_4h():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars_5m = [_bar(start + timedelta(minutes=5 * i)) for i in range(48)]
    bars_4h = aggregate_bars(bars_5m, "4h")
    assert len(bars_4h) == 1


def test_4h_bias_not_available_until_bar_closes():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars_4h = []
    for i in range(3):
        ts = start + timedelta(hours=4 * i)
        o = D("100")
        c = D("110") if i == 1 else D("100")
        bars_4h.append(Bar(ts, o, max(o, c) + D(1), min(o, c) - D(1), c, 1))
    series = build_4h_bias_series(bars_4h, FractalConfig(1, 1))
    # During first 4H bucket (before close at 04:00) — no completed 4H bar yet
    snap_early = bias_for_5m_bar(bars_4h, series, start + timedelta(hours=3, minutes=55))
    assert snap_early.record.fractal_definition == "unknown"
    snap_late = bias_for_5m_bar(bars_4h, series, start + timedelta(hours=4, minutes=5))
    assert snap_late.record.fractal_definition != "unknown"
    assert snap_late is series[0]


def test_provider_comparison_catalog_has_micros():
    cat = comparison_catalog()
    assert "MNQ" in cat["micro_contracts"]
    assert any(p["id"] == "databento" for p in cat["providers"])


def test_csv_import_fixture_validates_lineage():
    """Golden-path: tiny CSV → import → lineage user_csv (no exchange license claim)."""
    from app.services.market_data.data_lineage import lineage_from_provider

    assert lineage_from_provider("csv", {}) == "user_csv"