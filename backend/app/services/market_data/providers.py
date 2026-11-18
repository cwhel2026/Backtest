"""Market data provider adapters — never fabricate bars."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.core.config import get_settings


class ProviderConnectionState(str, Enum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ProviderHealth:
    slug: str
    display_name: str
    state: ProviderConnectionState
    message: str
    capabilities: dict


class MarketDataProvider(ABC):
    slug: str
    display_name: str

    @abstractmethod
    async def health(self) -> ProviderHealth:
        ...

    @abstractmethod
    async def ingest_historical(
        self,
        instrument_symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> dict:
        """Return ingestion job metadata; actual ingestion runs in Celery."""
        ...


class DatabentoProvider(MarketDataProvider):
    slug = "databento"
    display_name = "Databento"

    async def health(self) -> ProviderHealth:
        settings = get_settings()
        if not settings.databento_api_key:
            return ProviderHealth(
                slug=self.slug,
                display_name=self.display_name,
                state=ProviderConnectionState.NOT_CONFIGURED,
                message="Set DATABENTO_API_KEY in environment to enable licensed historical futures data.",
                capabilities={"ohlcv": True, "tick": True, "1m": True, "5m": True, "15m": True, "1h": True},
            )
        return ProviderHealth(
            slug=self.slug,
            display_name=self.display_name,
            state=ProviderConnectionState.CONFIGURED,
            message="API key present. Queue ingestion on Market Data to download GLBX.MDP3 OHLCV.",
            capabilities={"ohlcv": True, "tick": True, "1m": True, "5m": True, "15m": True, "1h": True},
        )

    async def ingest_historical(
        self, instrument_symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> dict:
        health = await self.health()
        if health.state == ProviderConnectionState.NOT_CONFIGURED:
            raise ValueError(health.message)
        return {
            "provider": self.slug,
            "instrument_symbol": instrument_symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "status": "queued",
            "note": "Worker downloads licensed 1m bars and stores your requested timeframe.",
        }


class YahooFinanceProvider(MarketDataProvider):
    slug = "yahoo"
    display_name = "Yahoo Finance (free)"

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            slug=self.slug,
            display_name=self.display_name,
            state=ProviderConnectionState.CONNECTED,
            message="No API key required. Delayed CME futures via Yahoo (e.g. MES=F). Research-only — not licensed.",
            capabilities={
                "ohlcv": True,
                "1m": True,
                "5m": True,
                "15m": True,
                "1h": True,
                "cost": "free",
                "max_range_days_1m": 7,
                "max_range_days_5m": 60,
            },
        )

    async def ingest_historical(
        self, instrument_symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> dict:
        return {
            "provider": self.slug,
            "instrument_symbol": instrument_symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "status": "queued",
            "note": "Worker pulls delayed Yahoo futures OHLCV and stores your timeframe.",
        }


class FinzDataProvider(MarketDataProvider):
    slug = "finzdata"
    display_name = "FinzData (historical futures)"

    async def health(self) -> ProviderHealth:
        settings = get_settings()
        if not settings.finzdata_configured:
            return ProviderHealth(
                slug=self.slug,
                display_name=self.display_name,
                state=ProviderConnectionState.NOT_CONFIGURED,
                message="Set FINZDATA_API_KEY. Free plan is daily bars; 1m/5m search needs a paid FinzData market.",
                capabilities={"ohlcv": True, "1m": True, "5m": True, "cost": "free_daily_or_paid_intraday"},
            )
        return ProviderHealth(
            slug=self.slug,
            display_name=self.display_name,
            state=ProviderConnectionState.CONFIGURED,
            message="API key present. Search tries FinzData 1m/5m then falls back to Yahoo if the plan is daily-only.",
            capabilities={"ohlcv": True, "1m": True, "5m": True, "continuous": True},
        )

    async def ingest_historical(
        self, instrument_symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> dict:
        health = await self.health()
        if health.state == ProviderConnectionState.NOT_CONFIGURED:
            raise ValueError(health.message)
        return {
            "provider": self.slug,
            "instrument_symbol": instrument_symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "status": "queued",
            "note": "Worker pulls continuous FinzData bars (US Eastern timestamps → UTC).",
        }


class TwelveDataProvider(MarketDataProvider):
    slug = "twelvedata"
    display_name = "Twelve Data (live CME)"

    async def health(self) -> ProviderHealth:
        settings = get_settings()
        if not settings.twelvedata_configured:
            return ProviderHealth(
                slug=self.slug,
                display_name=self.display_name,
                state=ProviderConnectionState.NOT_CONFIGURED,
                message="Set TWELVEDATA_API_KEY for cloud live/near-live NQ/ES 1m bars (paid real-time; free is delayed).",
                capabilities={"ohlcv": True, "1m": True, "5m": True, "quote": True, "live": True},
            )
        return ProviderHealth(
            slug=self.slug,
            display_name=self.display_name,
            state=ProviderConnectionState.CONFIGURED,
            message="API key present. Paper desk prefers Twelve Data over delayed Yahoo when IBKR is not connected.",
            capabilities={"ohlcv": True, "1m": True, "5m": True, "quote": True, "live": True},
        )

    async def ingest_historical(
        self, instrument_symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> dict:
        health = await self.health()
        if health.state == ProviderConnectionState.NOT_CONFIGURED:
            raise ValueError(health.message)
        return {
            "provider": self.slug,
            "instrument_symbol": instrument_symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "status": "queued",
            "note": "Worker pulls CME 1m/5m bars from Twelve Data.",
        }


class InteractiveBrokersProvider(MarketDataProvider):
    slug = "ibkr"
    display_name = "Interactive Brokers"

    async def health(self) -> ProviderHealth:
        settings = get_settings()
        if not settings.ibkr_configured:
            return ProviderHealth(
                slug=self.slug,
                display_name=self.display_name,
                state=ProviderConnectionState.NOT_CONFIGURED,
                message="Set IBKR_HOST (and IBKR_PORT) where the worker can reach your IB Gateway. This is true live CME data.",
                capabilities={"ohlcv": True, "1m": True, "5m": True, "requires_same_network": True},
            )
        return ProviderHealth(
            slug=self.slug,
            display_name=self.display_name,
            state=ProviderConnectionState.CONFIGURED,
            message=f"Gateway {settings.ibkr_host}:{settings.ibkr_port}. Paper desk uses this first for live 1m bars + last trade.",
            capabilities={"ohlcv": True, "1m": True, "5m": True, "requires_same_network": True},
        )

    async def ingest_historical(
        self, instrument_symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> dict:
        health = await self.health()
        if health.state == ProviderConnectionState.NOT_CONFIGURED:
            raise ValueError(health.message)
        return {
            "provider": self.slug,
            "instrument_symbol": instrument_symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "status": "queued",
            "note": "Worker must reach your IB Gateway on the same network/VPN.",
        }


PROVIDER_REGISTRY: dict[str, MarketDataProvider] = {
    InteractiveBrokersProvider.slug: InteractiveBrokersProvider(),
    TwelveDataProvider.slug: TwelveDataProvider(),
    FinzDataProvider.slug: FinzDataProvider(),
    YahooFinanceProvider.slug: YahooFinanceProvider(),
    DatabentoProvider.slug: DatabentoProvider(),
}


async def all_provider_health() -> list[ProviderHealth]:
    return [await p.health() for p in PROVIDER_REGISTRY.values()]