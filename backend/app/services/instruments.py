"""Instrument registry — curated liquid CME futures (prop-research focus)."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AssetClass
from app.models.instrument import Instrument

CME_INDEX_HOURS = {
    "sessions": [
        {"name": "RTH", "start": "08:30", "end": "15:15", "timezone": "America/Chicago"},
        {
            "name": "ETH",
            "start": "17:00",
            "end": "16:00",
            "timezone": "America/Chicago",
            "overnight": True,
        },
    ]
}

CME_GLOBEX_COMMODITY = {
    "sessions": [
        {
            "name": "ETH",
            "start": "17:00",
            "end": "16:00",
            "timezone": "America/Chicago",
            "overnight": True,
        },
    ]
}

# Curated set: major index + micro index + crude + gold (liquid, widely traded).
INSTRUMENT_SPECS: list[dict] = [
    {"symbol": "ES", "name": "E-mini S&P 500", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.25", "tick_value": "12.50", "multiplier": "50", "hours": CME_INDEX_HOURS},
    {"symbol": "MES", "name": "Micro E-mini S&P 500", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.25", "tick_value": "1.25", "multiplier": "5", "hours": CME_INDEX_HOURS, "micro_of": "ES", "is_micro": True},
    {"symbol": "NQ", "name": "E-mini Nasdaq-100", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.25", "tick_value": "5.00", "multiplier": "20", "hours": CME_INDEX_HOURS},
    {"symbol": "MNQ", "name": "Micro E-mini Nasdaq-100", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.25", "tick_value": "0.50", "multiplier": "2", "hours": CME_INDEX_HOURS, "micro_of": "NQ", "is_micro": True},
    {"symbol": "CL", "name": "Crude Oil (WTI)", "asset_class": AssetClass.ENERGY, "tick_size": "0.01", "tick_value": "10.00", "multiplier": "1000", "hours": CME_GLOBEX_COMMODITY},
    {"symbol": "GC", "name": "Gold", "asset_class": AssetClass.METAL, "tick_size": "0.10", "tick_value": "10.00", "multiplier": "100", "hours": CME_GLOBEX_COMMODITY},
]

CURATED_SYMBOLS = frozenset(s["symbol"] for s in INSTRUMENT_SPECS)


def _instrument_from_spec(spec: dict) -> Instrument:
    return Instrument(
        symbol=spec["symbol"],
        name=spec["name"],
        asset_class=spec["asset_class"],
        tick_size=Decimal(spec["tick_size"]),
        tick_value=Decimal(spec["tick_value"]),
        multiplier=Decimal(spec["multiplier"]),
        trading_hours=spec["hours"],
        micro_of=spec.get("micro_of"),
        is_micro=spec.get("is_micro", False),
        is_active=True,
        metadata_extra={
            "source": "CME contract specifications (curated seed)",
            "verify_url": "https://www.cmegroup.com/markets.html",
        },
    )


async def sync_instrument_catalog(session: AsyncSession) -> int:
    """Insert missing curated symbols; hide everything else from dropdowns (is_active=False)."""
    spec_by_symbol = {s["symbol"]: s for s in INSTRUMENT_SPECS}
    result = await session.execute(select(Instrument))
    existing = {i.symbol: i for i in result.scalars().all()}

    changed = 0
    for symbol, spec in spec_by_symbol.items():
        if symbol not in existing:
            session.add(_instrument_from_spec(spec))
            changed += 1
        elif not existing[symbol].is_active:
            existing[symbol].is_active = True
            changed += 1

    for sym, inst in existing.items():
        if sym not in spec_by_symbol and inst.is_active:
            inst.is_active = False
            changed += 1

    await session.flush()
    return changed


async def seed_instruments(session: AsyncSession) -> int:
    return await sync_instrument_catalog(session)