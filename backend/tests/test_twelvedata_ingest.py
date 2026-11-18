from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.enums import AssetClass
from app.models.instrument import Instrument
from app.services.market_data.live_feed import classify_feed_quality, live_source_chain
from app.services.market_data.twelvedata_ingest import (
    bars_from_payload,
    quote_from_payload,
    twelvedata_symbol,
)
from app.services.paper_engine import OpenTrade, SlotCursor, exit_open_on_quote


def test_twelvedata_symbol_roots():
    assert twelvedata_symbol("nq") == "NQ"
    assert twelvedata_symbol("/MNQ") == "MNQ"


def test_bars_from_payload_utc():
    payload = {
        "status": "ok",
        "meta": {"exchange_timezone": "UTC"},
        "values": [
            {
                "datetime": "2026-11-18 15:01:00",
                "open": "19010.00",
                "high": "19014.25",
                "low": "19009.50",
                "close": "19012.25",
                "volume": "120",
            }
        ],
    }
    bars = bars_from_payload(payload, tz_name="UTC")
    assert len(bars) == 1
    assert bars[0].close == Decimal("19012.25")
    assert bars[0].ts.tzinfo is not None
    assert bars[0].ts.hour == 15


def test_quote_from_payload():
    quote = quote_from_payload(
        {
            "symbol": "NQ",
            "datetime": "2026-11-18 15:01:12",
            "close": "19012.50",
            "open": "19010.00",
            "high": "19014.00",
            "low": "19009.00",
            "volume": "80",
        },
        tz_name="UTC",
    )
    assert quote["last"] == 19012.5
    assert quote["source"] == "twelvedata"


def test_classify_live_vs_delayed():
    now = datetime.now(UTC)
    assert classify_feed_quality(now - timedelta(seconds=20), session_open=True, provider="twelvedata") == "live"
    assert classify_feed_quality(now - timedelta(minutes=12), session_open=True, provider="yahoo") == "delayed"
    assert classify_feed_quality(now - timedelta(seconds=20), session_open=True, provider="yahoo") == "delayed"


def test_live_source_chain_ends_with_yahoo():
    chain = live_source_chain()
    assert chain[-1] == "yahoo"
    assert "ibkr" not in chain or chain[0] == "ibkr"


def test_exit_open_on_quote_hits_stop():
    inst = Instrument(
        symbol="NQ",
        name="E-mini Nasdaq",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("5"),
        multiplier=Decimal("20"),
        trading_hours={},
        default_commission_per_side=Decimal("2.15"),
    )
    start = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)
    pos = OpenTrade("long", 1, Decimal("19000"), Decimal("18990"), Decimal("19100"), start, 2, Decimal("200"))
    cursor, fills = exit_open_on_quote(
        inst,
        SlotCursor(start, pos),
        Decimal("18990"),
        start + timedelta(seconds=12),
        slip_ticks=0,
    )
    assert cursor.position is None
    assert len(fills) == 1
    assert fills[0].exit_reason == "stop_loss"
