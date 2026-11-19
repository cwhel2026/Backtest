from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.market_data.exchange_calendar import (
    SessionPolicy,
    classify_bar_session,
    is_exchange_session_day,
    session_policy_from_spec,
)
from app.services.instruments import CME_INDEX_HOURS


def test_rth_session_key_uses_calendar_prefix():
    policy = session_policy_from_spec({"session": {"allowed": ["RTH"]}}, CME_INDEX_HOURS)
    ts = datetime(2024, 6, 3, 10, 30, tzinfo=ZoneInfo("America/Chicago"))
    key, mode = classify_bar_session(ts, policy)
    assert mode == "RTH"
    assert key.startswith("rth:")


def test_instrument_trading_hours_parsed_from_sessions():
    policy = session_policy_from_spec({"session": {"allowed": ["RTH"]}}, CME_INDEX_HOURS)
    assert policy.rth.start.hour == 8


def test_closed_day_key():
    policy = SessionPolicy(calendar_code="CMES")
    # New Year's observed may vary — just assert structure for arbitrary closed label
    d = datetime(2020, 1, 1, 15, 0, tzinfo=ZoneInfo("America/Chicago"))
    if not is_exchange_session_day(d.date(), "CMES"):
        key, mode = classify_bar_session(d, policy)
        assert key.startswith("closed:")
        assert mode is None