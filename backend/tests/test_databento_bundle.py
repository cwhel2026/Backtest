from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.services.instruments import PRIMARY_RESEARCH_SYMBOLS
from app.services.market_data.databento_client import (
    DEFAULT_HISTORY_DAYS,
    iter_download_chunks,
    quote_bundle_cost,
    default_research_window,
)


def test_primary_research_symbols():
    assert PRIMARY_RESEARCH_SYMBOLS == frozenset({"MNQ", "MES", "MGC"})


def test_default_research_window_five_years():
    start, end = default_research_window()
    days = (end - start).days
    assert days >= DEFAULT_HISTORY_DAYS - 2


def test_iter_download_chunks():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 2, 15, tzinfo=UTC)
    chunks = list(iter_download_chunks(start, end, chunk_days=21))
    assert len(chunks) >= 2
    assert chunks[0][0] == start
    assert chunks[-1][1] == end


@patch("app.services.market_data.databento_client.quote_download_cost")
def test_quote_bundle_sums(mock_quote):
    mock_quote.side_effect = lambda sym, *_a, **_k: MagicMock(
        usd=10.0,
        to_dict=lambda: {"estimated_usd": 10.0, "databento_symbol": f"{sym}.c.0"},
        gbp=8.0,
        gbp_rate=1.25,
    )
    start = datetime(2021, 11, 1, tzinfo=UTC)
    end = datetime(2026, 11, 1, tzinfo=UTC)
    out = quote_bundle_cost(["MNQ", "MES", "MGC"], start, end)
    assert out["estimated_usd_total"] == 30.0
    assert set(out["symbols"]) == {"MNQ", "MES", "MGC"}