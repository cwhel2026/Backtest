from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.services.paper_book import strategy_fingerprint
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
    pos = OpenTrade(
        "long",
        1,
        Decimal("19000"),
        Decimal("19000"),
        Decimal("18800"),
        Decimal("19500"),
        bars[0].ts,
        3,
        Decimal("200"),
    )
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
