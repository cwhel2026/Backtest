"""Optional live Databento smoke — NEVER downloads paid data by default.

Set DATABENTO_LIVE_SMOKE=true and DATABENTO_API_KEY to run cost-only probe.
Paid range download requires DATABENTO_LIVE_CONFIRM=yes (not implemented here).
"""

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.services.market_data.databento_client import quote_download_cost


@pytest.mark.skipif(
    not (get_settings().databento_live_smoke and get_settings().databento_configured),
    reason="Live smoke disabled — set DATABENTO_LIVE_SMOKE=true and DATABENTO_API_KEY",
)
def test_live_get_cost_smoke_only():
    """Calls metadata.get_cost only — does not call timeseries.get_range."""
    end = datetime.now(UTC)
    start = end - timedelta(days=1)
    q = quote_download_cost("MES", start, end)
    assert q.source == "databento.get_cost"
    assert q.usd >= 0
    assert os.environ.get("DATABENTO_LIVE_CONFIRM") != "yes"  # guard: no download path in this test