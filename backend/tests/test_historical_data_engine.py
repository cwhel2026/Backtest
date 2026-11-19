"""Historical Data Engine 3.0 — synthetic/fixture tests (no paid API calls)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.backtest.bars import Bar, aggregate_bars
from app.services.market_data.budget import get_or_create_month, month_key, reserve_approval
from app.services.market_data.databento_client import DATABENTO_ROOT_SYMBOLS, quote_download_cost, validate_root_symbol
from app.services.market_data.dataset_catalog import ingest_fingerprint
from app.services.market_data.ohlcv_parquet import checksum_sha256, set_store_dir, write_bars
from app.services.market_data.validate_dataset import (
    classify_quality,
    extended_audit,
    video_strategy_readiness,
)
from app.services.market_data.quality import DatasetQualityReport


def test_databento_symbol_validation():
    validate_root_symbol("mnq")
    with pytest.raises(ValueError):
        validate_root_symbol("XYZ")


def test_micro_roots_catalog():
    assert "MNQ" in DATABENTO_ROOT_SYMBOLS
    assert "MGC" in DATABENTO_ROOT_SYMBOLS


def test_ingest_fingerprint_stable():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 2, 1, tzinfo=UTC)
    a = ingest_fingerprint(
        provider_slug="databento", instrument_symbol="MES", timeframe="5m", start=start, end=end
    )
    b = ingest_fingerprint(
        provider_slug="databento", instrument_symbol="MES", timeframe="5m", start=start, end=end
    )
    assert a == b


def test_aggregate_30m_deterministic():
    start = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    bars = [
        Bar(
            ts=start + timedelta(minutes=i),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=10,
        )
        for i in range(60)
    ]
    out = aggregate_bars(bars, "30m")
    assert len(out) == 2
    assert out[0].ts == start


def test_quality_classify_blocked_on_duplicates():
    report = DatasetQualityReport(
        10,
        2,
        0,
        0,
        [],
        ["dupes"],
        datetime.now(UTC),
        datetime.now(UTC),
    )
    q, _ = classify_quality(report, symbol="MES", timeframe="5m")
    assert q == "blocked"


def test_video_readiness_insufficient():
    bars = [
        Bar(
            ts=datetime(2024, 6, 3, 13, 30, tzinfo=UTC) + timedelta(minutes=5 * i),
            open=Decimal(1),
            high=Decimal(2),
            low=Decimal(0.5),
            close=Decimal(1),
            volume=1,
        )
        for i in range(20)
    ]
    r = video_strategy_readiness(bars, symbol="MES", timeframe="5m")
    assert r["video_liquidity_sweep"]["ready"] is False


def test_parquet_checksum(tmp_path):
    set_store_dir(tmp_path)
    ds_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    ts = datetime(2024, 1, 2, 14, 0, tzinfo=UTC)
    write_bars(ds_id, [(ts, Decimal(1), Decimal(2), Decimal(0.5), Decimal(1.5), 100)])
    h1 = checksum_sha256(ds_id)
    h2 = checksum_sha256(ds_id)
    assert h1 == h2
    assert len(h1) == 64


def test_quote_without_api_key_heuristic():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 11, tzinfo=UTC)
    q = quote_download_cost("MES", start, end, api_key="")
    assert q.source == "heuristic"
    assert q.usd > 0


@patch("app.services.market_data.databento_client.client")
def test_quote_with_mocked_get_cost(mock_client_factory):
    mock_client = MagicMock()
    mock_client.metadata.get_cost.return_value = 12.34
    mock_client_factory.return_value = mock_client
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 5, tzinfo=UTC)
    q = quote_download_cost("MNQ", start, end, api_key="test-key", gbp_usd_rate=1.25)
    assert q.source == "databento.get_cost"
    assert q.usd == 12.34
    assert q.gbp is not None


def test_budget_reserve_logic():
    from app.models.market_data import ResearchDataBudgetMonth

    row = ResearchDataBudgetMonth(
        month_key="2099-01",
        budget_gbp=Decimal("50"),
        estimated_usd=Decimal(0),
        approved_usd=Decimal(0),
        actual_usd=Decimal(0),
    )
    spend = float(row.approved_usd_to_gbp_equiv(1.25))
    assert spend == 0.0
    row.approved_usd = Decimal("100")
    spend = float(row.approved_usd_to_gbp_equiv(1.25))
    assert spend == 80.0
    assert spend > float(row.budget_gbp)