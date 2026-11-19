"""Provider stubs — configuration and documentation only until credentials exist."""

from __future__ import annotations

from app.core.config import get_settings
from app.services.live_lab.market_data.base import LiveMarketDataAdapter
from app.services.live_lab.types import MarketEvent


class _UnverifiedAdapter(LiveMarketDataAdapter):
    def __init__(self, provider_id: str, docs_url: str, config_keys: list[str]):
        self.provider_id = provider_id
        self._docs_url = docs_url
        self._config_keys = config_keys

    def describe(self) -> dict:
        settings = get_settings()
        missing = [k for k in self._config_keys if not getattr(settings, k, None)]
        return {
            "provider": self.provider_id,
            "verified": False,
            "documentation": self._docs_url,
            "missing_config": missing,
            "note": "Live connectivity not tested in development — configure credentials on Railway.",
        }

    def connect(self) -> None:
        raise RuntimeError(f"{self.provider_id}: live adapter not implemented without verified credentials")

    def disconnect(self) -> None:
        pass

    def poll_events(self, limit: int = 500) -> list[MarketEvent]:
        return []


class DatabentoLiveAdapter(_UnverifiedAdapter):
    def __init__(self) -> None:
        super().__init__(
            "databento_live",
            "https://databento.com/docs/api-reference-live",
            ["databento_api_key"],
        )


class IbkrTwsAdapter(_UnverifiedAdapter):
    def __init__(self) -> None:
        super().__init__(
            "ibkr_tws",
            "https://interactivebrokers.github.io/tws-api/",
            ["ibkr_host"],
        )


class CmeWebSocketAdapter(_UnverifiedAdapter):
    def __init__(self) -> None:
        super().__init__(
            "cme_websocket",
            "https://www.cmegroup.com/market-data/real-time-market-data-apis.html",
            [],
        )