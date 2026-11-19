"""Verify Databento client calls match official SDK signatures (no network)."""

import inspect
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from databento.historical.api.metadata import MetadataHttpAPI
from databento.historical.api.timeseries import TimeseriesHttpAPI

from app.services.market_data.contract_series import PriceSeriesKind, SeriesSelection
from app.services.market_data.databento_client import (
    DATABENTO_FUTURES_DATASET,
    DATABENTO_OHLCV_SCHEMA,
    fetch_ohlcv_1m_with_retries,
    quote_download_cost,
)


def test_historical_client_exposes_metadata_get_cost():
    sig = inspect.signature(MetadataHttpAPI.get_cost)
    assert "dataset" in sig.parameters
    assert "schema" in sig.parameters
    assert "stype_in" in sig.parameters


def test_get_range_uses_ohlcv_1m_schema():
    sig = inspect.signature(TimeseriesHttpAPI.get_range)
    for name in ("dataset", "schema", "symbols", "start", "end", "stype_in", "stype_out"):
        assert name in sig.parameters


@patch("app.services.market_data.databento_client.client")
def test_quote_forwards_official_params(mock_client_factory):
    mock_client = MagicMock()
    mock_client.metadata.get_cost.return_value = 3.5
    mock_client_factory.return_value = mock_client
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = datetime(2024, 6, 2, tzinfo=UTC)
    q = quote_download_cost("MES", start, end, api_key="k")
    assert q.usd == 3.5
    mock_client.metadata.get_cost.assert_called_once()
    kwargs = mock_client.metadata.get_cost.call_args.kwargs
    assert kwargs["dataset"] == DATABENTO_FUTURES_DATASET
    assert kwargs["schema"] == DATABENTO_OHLCV_SCHEMA
    assert kwargs["stype_in"] == "continuous"
    assert kwargs["symbols"] == "MES.c.0"


@patch("app.services.market_data.databento_client.client")
def test_fetch_uses_continuous_unadjusted_by_default(mock_client_factory):
    mock_client = MagicMock()
    store = MagicMock()
    store.to_df.return_value = __import__("pandas").DataFrame()
    store.metadata = None
    mock_client.timeseries.get_range.return_value = store
    mock_client_factory.return_value = mock_client
    start = datetime(2024, 6, 1, 13, 30, tzinfo=UTC)
    end = datetime(2024, 6, 1, 14, 0, tzinfo=UTC)
    bars, meta = fetch_ohlcv_1m_with_retries(
        "MES",
        start,
        end,
        api_key="k",
        series=SeriesSelection(root="MES", kind=PriceSeriesKind.CONTINUOUS_UNADJUSTED),
    )
    assert bars == []
    assert meta["back_adjusted"] is False
    assert meta["price_stitching"] is False
    kw = mock_client.timeseries.get_range.call_args.kwargs
    assert kw["stype_in"] == "continuous"
    assert kw["symbols"] == "MES.c.0"