from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.services.market_data.quality import audit_bars, estimate_download_cost_usd


def test_audit_detects_duplicate_and_gap():
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [
        Bar(t0, Decimal(1), Decimal(2), Decimal("0.5"), Decimal(1.5), 1),
        Bar(t0, Decimal(1), Decimal(2), Decimal("0.5"), Decimal(1.5), 1),
        Bar(t0 + timedelta(minutes=15), Decimal(1), Decimal(2), Decimal("0.5"), Decimal(1.5), 1),
    ]
    report = audit_bars(bars, timeframe="5m", source="fixture")
    assert report.duplicates == 1
    assert report.gaps
    assert "not filled" in " ".join(report.warnings).lower()


def test_paid_provider_requires_approval_flag():
    est = estimate_download_cost_usd("finzdata", symbols=2, days=30, timeframe="1m")
    assert est.get("requires_approval") is True
    assert est["estimated_usd"] > 0


def test_yahoo_free_estimate():
    est = estimate_download_cost_usd("yahoo", symbols=1, days=7, timeframe="1m")
    assert est["estimated_usd"] == 0.0