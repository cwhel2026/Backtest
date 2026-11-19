from datetime import UTC, datetime

from app.services.market_data.finzdata_ingest import bars_from_payload, finzdata_root, interval_for_timeframe


def test_root_and_interval():
    assert finzdata_root("/mnq") == "MNQ"
    assert interval_for_timeframe("5m") == "5min"
    assert interval_for_timeframe("1m") == "1min"


def test_parse_eastern_naive_timestamps():
    payload = {
        "data": [
            {
                "timestamp": "2024-06-03 09:30:00",
                "open": 19000.25,
                "high": 19001.0,
                "low": 18999.5,
                "close": 19000.75,
                "volume": 12,
            }
        ]
    }
    bars = bars_from_payload(payload)
    assert len(bars) == 1
    assert bars[0].ts.tzinfo is not None
    assert bars[0].ts.astimezone(UTC).hour in (13, 14)
    assert bars[0].volume == 12


def test_parse_list_payload():
    payload = [
        {
            "date": "2024-06-03T13:30:00Z",
            "Open": "100",
            "High": "101",
            "Low": "99",
            "Close": "100.5",
            "Volume": "8",
        }
    ]
    bars = bars_from_payload(payload)
    assert len(bars) == 1
    assert float(bars[0].close) == 100.5
