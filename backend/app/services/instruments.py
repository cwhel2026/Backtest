"""Instrument registry seed data — CME contract specifications (verify via exchange docs)."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AssetClass
from app.models.instrument import Instrument

# CME Globex regular session template (simplified; holidays in metadata_extra)
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

CME_GLOBEX_METALS = {
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

INSTRUMENT_SPECS: list[dict] = [
    # Equity index
    {"symbol": "ES", "name": "E-mini S&P 500", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.25", "tick_value": "12.50", "multiplier": "50", "hours": CME_INDEX_HOURS},
    {"symbol": "MES", "name": "Micro E-mini S&P 500", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.25", "tick_value": "1.25", "multiplier": "5", "hours": CME_INDEX_HOURS, "micro_of": "ES", "is_micro": True},
    {"symbol": "NQ", "name": "E-mini Nasdaq-100", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.25", "tick_value": "5.00", "multiplier": "20", "hours": CME_INDEX_HOURS},
    {"symbol": "MNQ", "name": "Micro E-mini Nasdaq-100", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.25", "tick_value": "0.50", "multiplier": "2", "hours": CME_INDEX_HOURS, "micro_of": "NQ", "is_micro": True},
    {"symbol": "YM", "name": "E-mini Dow", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "1.0", "tick_value": "5.00", "multiplier": "5", "hours": CME_INDEX_HOURS},
    {"symbol": "MYM", "name": "Micro E-mini Dow", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "1.0", "tick_value": "0.50", "multiplier": "0.5", "hours": CME_INDEX_HOURS, "micro_of": "YM", "is_micro": True},
    {"symbol": "RTY", "name": "E-mini Russell 2000", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.10", "tick_value": "5.00", "multiplier": "50", "hours": CME_INDEX_HOURS},
    {"symbol": "M2K", "name": "Micro E-mini Russell 2000", "asset_class": AssetClass.EQUITY_INDEX, "tick_size": "0.10", "tick_value": "0.50", "multiplier": "5", "hours": CME_INDEX_HOURS, "micro_of": "RTY", "is_micro": True},
    # Metals
    {"symbol": "GC", "name": "Gold", "asset_class": AssetClass.METAL, "tick_size": "0.10", "tick_value": "10.00", "multiplier": "100", "hours": CME_GLOBEX_METALS},
    {"symbol": "MGC", "name": "Micro Gold", "asset_class": AssetClass.METAL, "tick_size": "0.10", "tick_value": "1.00", "multiplier": "10", "hours": CME_GLOBEX_METALS, "micro_of": "GC", "is_micro": True},
    {"symbol": "SI", "name": "Silver", "asset_class": AssetClass.METAL, "tick_size": "0.005", "tick_value": "25.00", "multiplier": "5000", "hours": CME_GLOBEX_METALS},
    {"symbol": "SIL", "name": "Micro Silver", "asset_class": AssetClass.METAL, "tick_size": "0.005", "tick_value": "5.00", "multiplier": "1000", "hours": CME_GLOBEX_METALS, "micro_of": "SI", "is_micro": True},
    # Energy
    {"symbol": "CL", "name": "Crude Oil", "asset_class": AssetClass.ENERGY, "tick_size": "0.01", "tick_value": "10.00", "multiplier": "1000", "hours": CME_GLOBEX_METALS},
    {"symbol": "MCL", "name": "Micro Crude Oil", "asset_class": AssetClass.ENERGY, "tick_size": "0.01", "tick_value": "1.00", "multiplier": "100", "hours": CME_GLOBEX_METALS, "micro_of": "CL", "is_micro": True},
    {"symbol": "NG", "name": "Natural Gas", "asset_class": AssetClass.ENERGY, "tick_size": "0.001", "tick_value": "10.00", "multiplier": "10000", "hours": CME_GLOBEX_METALS},
    # Currency
    {"symbol": "6E", "name": "Euro FX", "asset_class": AssetClass.CURRENCY, "tick_size": "0.00005", "tick_value": "6.25", "multiplier": "125000", "hours": CME_GLOBEX_METALS},
    {"symbol": "M6E", "name": "Micro EUR/USD", "asset_class": AssetClass.CURRENCY, "tick_size": "0.0001", "tick_value": "1.25", "multiplier": "12500", "hours": CME_GLOBEX_METALS, "micro_of": "6E", "is_micro": True},
    {"symbol": "6B", "name": "British Pound", "asset_class": AssetClass.CURRENCY, "tick_size": "0.0001", "tick_value": "6.25", "multiplier": "62500", "hours": CME_GLOBEX_METALS},
    {"symbol": "M6B", "name": "Micro GBP/USD", "asset_class": AssetClass.CURRENCY, "tick_size": "0.0001", "tick_value": "0.625", "multiplier": "6250", "hours": CME_GLOBEX_METALS, "micro_of": "6B", "is_micro": True},
    {"symbol": "6J", "name": "Japanese Yen", "asset_class": AssetClass.CURRENCY, "tick_size": "0.0000005", "tick_value": "6.25", "multiplier": "12500000", "hours": CME_GLOBEX_METALS},
    {"symbol": "6A", "name": "Australian Dollar", "asset_class": AssetClass.CURRENCY, "tick_size": "0.0001", "tick_value": "10.00", "multiplier": "100000", "hours": CME_GLOBEX_METALS},
    {"symbol": "6C", "name": "Canadian Dollar", "asset_class": AssetClass.CURRENCY, "tick_size": "0.00005", "tick_value": "5.00", "multiplier": "100000", "hours": CME_GLOBEX_METALS},
    {"symbol": "6S", "name": "Swiss Franc", "asset_class": AssetClass.CURRENCY, "tick_size": "0.0001", "tick_value": "12.50", "multiplier": "125000", "hours": CME_GLOBEX_METALS},
    {"symbol": "6N", "name": "New Zealand Dollar", "asset_class": AssetClass.CURRENCY, "tick_size": "0.0001", "tick_value": "10.00", "multiplier": "100000", "hours": CME_GLOBEX_METALS},
]


async def seed_instruments(session: AsyncSession) -> int:
    result = await session.execute(select(Instrument).limit(1))
    if result.scalar_one_or_none():
        return 0

    for spec in INSTRUMENT_SPECS:
        session.add(
            Instrument(
                symbol=spec["symbol"],
                name=spec["name"],
                asset_class=spec["asset_class"],
                tick_size=Decimal(spec["tick_size"]),
                tick_value=Decimal(spec["tick_value"]),
                multiplier=Decimal(spec["multiplier"]),
                trading_hours=spec["hours"],
                micro_of=spec.get("micro_of"),
                is_micro=spec.get("is_micro", False),
                metadata_extra={
                    "source": "CME contract specifications (seed)",
                    "verify_url": "https://www.cmegroup.com/markets.html",
                },
            )
        )
    await session.flush()
    return len(INSTRUMENT_SPECS)