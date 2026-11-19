"""Live market data adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from app.services.live_lab.types import MarketEvent


class LiveMarketDataAdapter(ABC):
    """Pull or stream market events. Implementations must label latency_mode honestly."""

    provider_id: str

    @abstractmethod
    def describe(self) -> dict:
        """Human-readable status and licensing notes."""

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def poll_events(self, limit: int = 500) -> list[MarketEvent]:
        """Return newly available events since last poll (adapter may buffer)."""

    def heartbeat(self) -> bool:
        return True