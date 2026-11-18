from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.backtest.bars import Bar
from app.services.paper_book import globex_session, scan_headline, scanner_payload, strategy_fingerprint
from app.services.paper_engine import OpenTrade, SlotCursor, advance_slot
from app.models.enums import AssetClass
from app.models.instrument import Instrument


def _atr_spec(name: str, stop_ticks: int = 16) -> dict:
    return {
        "name": name,
        "instrument_symbol": "NQ",
        "timeframe": "1m",
        "category": "atr_pullback",
        "entry": {"type": "ema_pullback", "fast_period": 9, "slow_period": 26},
        "exit": {
            "stop_ticks": stop_ticks,
            "target_ticks": 24,
            "stop_atr": 1.0,
            "target_atr": 2.0,
        },
    }


def test_fingerprint_collapses_refine_duplicate():
    a = strategy_fingerprint(_atr_spec("NQ ATR pull 9/26 1.0/2.0A"))
    b = strategy_fingerprint(_atr_spec("NQ ATR pull 9/26 1.0/2.0A refine 14/24"))
    assert a == b


def test_fingerprint_differs_across_markets():
    nq = _atr_spec("x")
    mnq = {**nq, "instrument_symbol": "MNQ"}
    assert strategy_fingerprint(nq) != strategy_fingerprint(mnq)


def test_open_trade_preserves_bars_held_across_ticks():
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
    start = datetime(2024, 6, 3, 14, 0, tzinfo=UTC)
    bars = [
        Bar(start, Decimal("19000"), Decimal("19002"), Decimal("18998"), Decimal("19001"), 10),
        Bar(start + timedelta(minutes=1), Decimal("19001"), Decimal("19003"), Decimal("18999"), Decimal("19002"), 10),
    ]
    pos = OpenTrade("long", 1, Decimal("19000"), Decimal("18800"), Decimal("19500"), bars[0].ts, 3, Decimal("200"))
    cursor, fills = advance_slot(
        {
            "entry": {"type": "ema_crossover", "fast_period": 3, "slow_period": 5},
            "exit": {"stop_ticks": 800, "target_ticks": 800, "session_end_flatten": False},
            "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
        },
        bars,
        inst,
        SlotCursor(bars[0].ts, pos),
        allow_entries=False,
    )
    assert fills == []
    assert cursor.position is not None
    assert cursor.position.bars_held >= 3


def test_globex_session_rth_and_weekend():
    chicago = ZoneInfo("America/Chicago")
    rth = datetime(2026, 11, 18, 10, 15, tzinfo=chicago)
    sat = datetime(2026, 11, 21, 12, 0, tzinfo=chicago)
    halt = datetime(2026, 11, 18, 16, 20, tzinfo=chicago)
    assert globex_session(rth)["state"] == "rth"
    assert globex_session(rth)["open"] is True
    assert globex_session(sat)["open"] is False
    assert globex_session(halt)["state"] == "halt"


def test_scan_headline_watching_next_bar():
    text = scan_headline(
        slot_count=1,
        opened=0,
        closed=0,
        enrolled_new=0,
        watches=[
            {
                "symbol": "NQ",
                "timeframe": "1m",
                "last_close": 19012.25,
                "new_bars": 1,
                "in_trade": False,
            }
        ],
        session={"open": True, "label": "RTH"},
    )
    assert "NQ" in text
    assert "no entry" in text.lower()


def test_scan_headline_armed_first_tick():
    text = scan_headline(
        slot_count=1,
        opened=0,
        closed=0,
        enrolled_new=1,
        watches=[{"symbol": "NQ", "timeframe": "1m", "last_close": 19012.25, "armed": True}],
        session={"open": True, "label": "RTH"},
    )
    assert "Armed" in text
    assert "Enrolled 1 keeper" in text


def test_scanner_payload_live_when_recent():
    now = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)
    payload = scanner_payload(
        last_scan={
            "at": (now - timedelta(seconds=12)).isoformat(),
            "headline": "Caught up on NQ 1m @ 19012.25 — watching for the next bar.",
            "opened": 0,
            "closed": 0,
            "refreshed": 1,
            "watches": [{"new_bars": 0}],
            "session": {"state": "rth", "label": "RTH", "open": True, "chicago": "09:00:00 CT"},
        },
        enrolled=[{"in_trade": False, "last_close": 19012.25, "symbol": "NQ", "timeframe": "1m"}],
        now=now,
    )
    assert payload["live"] is True
    assert payload["status"] == "scanning"
    assert payload["last_scan_age_sec"] == 12
    assert payload["next_scan_sec"] == 8
    assert "watching" in payload["headline"].lower() or "Caught up" in payload["headline"]
