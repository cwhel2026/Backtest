"""Futures-specific tick value and position sizing calculations."""

from decimal import Decimal

from app.models.instrument import Instrument


def dollars_per_point(instrument: Instrument) -> Decimal:
    """Point = 1.0 in price terms; dollars = multiplier for most CME products."""
    return instrument.multiplier


def risk_dollars(price_distance: Decimal, instrument: Instrument) -> Decimal:
    """Risk in USD for a price move of `price_distance` (in price units, not ticks)."""
    ticks = price_distance / instrument.tick_size
    return ticks * instrument.tick_value


def contracts_for_risk(
    entry_price: Decimal,
    stop_price: Decimal,
    dollar_risk: Decimal,
    instrument: Instrument,
) -> int:
    per_contract = risk_dollars(abs(entry_price - stop_price), instrument)
    if per_contract <= 0:
        return 0
    return int(dollar_risk // per_contract)


def commission_round_trip(instrument: Instrument) -> Decimal:
    return instrument.default_commission_per_side * 2