from datetime import UTC, datetime, timedelta

from app.services.market_data.yahoo_ingest import (
    choose_yahoo_download_timeframe,
    yahoo_futures_ticker,
)


def test_yahoo_ticker():
    assert yahoo_futures_ticker("mes") == "MES=F"


def test_choose_interval_for_seven_day_five_minute_target():
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = start + timedelta(days=6)
    assert choose_yahoo_download_timeframe(start, end, "5m") == "5m"


def test_choose_interval_for_seven_day_one_minute_target():
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = start + timedelta(days=6)
    assert choose_yahoo_download_timeframe(start, end, "1m") == "1m"


def test_choose_interval_for_thirty_day_window():
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = start + timedelta(days=30)
    assert choose_yahoo_download_timeframe(start, end, "5m") == "5m"