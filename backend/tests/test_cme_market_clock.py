from datetime import UTC, datetime

from app.services.cme_market_clock import cme_futures_market_status


def test_saturday_cmes_not_session_day():
    sat = datetime(2026, 11, 21, 18, 0, tzinfo=UTC)
    out = cme_futures_market_status(now=sat)
    assert out["session_day"] is False
    assert out["market_open_now"] is False
    assert "closed" in out["status"]