"""Sync instrument catalog seed for integration tests and workers."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instrument import Instrument
from app.services.instruments import INSTRUMENT_SPECS, _instrument_from_spec


def seed_instruments_sync(session: Session) -> int:
    spec_by_symbol = {s["symbol"]: s for s in INSTRUMENT_SPECS}
    existing = {i.symbol: i for i in session.execute(select(Instrument)).scalars().all()}
    changed = 0
    for symbol, spec in spec_by_symbol.items():
        if symbol not in existing:
            session.add(_instrument_from_spec(spec))
            changed += 1
    session.flush()
    return changed