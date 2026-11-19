"""Verified MNQ/MES/MGC contract specs and fee validation."""

from __future__ import annotations

from decimal import Decimal

from app.models.instrument import Instrument
from app.services.instruments import INSTRUMENT_SPECS, PRIMARY_RESEARCH_SYMBOLS

SPEC_BY_SYMBOL = {s["symbol"]: s for s in INSTRUMENT_SPECS if s["symbol"] in PRIMARY_RESEARCH_SYMBOLS}

FEE_SCHEDULE_VERSION = "prop_edge_micro_v1"
DEFAULT_COMMISSION_PER_SIDE = {
    "MNQ": Decimal("0.62"),
    "MES": Decimal("0.62"),
    "MGC": Decimal("0.62"),
}


def contract_spec(symbol: str) -> dict:
    sym = symbol.upper()
    if sym not in SPEC_BY_SYMBOL:
        raise ValueError(f"Missing contract specification for {sym}")
    return SPEC_BY_SYMBOL[sym]


def validate_instrument_accounting(instrument: Instrument) -> list[str]:
    """Return errors if tick/multiplier/P&L math may be wrong."""
    errors: list[str] = []
    spec = SPEC_BY_SYMBOL.get(instrument.symbol.upper())
    if not spec:
        return [f"No curated spec for {instrument.symbol}"]
    if instrument.tick_size != Decimal(spec["tick_size"]):
        errors.append(f"tick_size mismatch {instrument.tick_size} != {spec['tick_size']}")
    if instrument.multiplier != Decimal(spec["multiplier"]):
        errors.append(f"multiplier mismatch {instrument.multiplier} != {spec['multiplier']}")
    tick_value = instrument.tick_size * instrument.multiplier
    if instrument.tick_value != tick_value:
        errors.append(f"tick_value should be tick*mult={tick_value}, got {instrument.tick_value}")
    return errors


def dollars_per_point(instrument: Instrument) -> Decimal:
    return instrument.multiplier