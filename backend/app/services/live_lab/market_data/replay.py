"""Deterministic historical replay adapter for forward-test verification."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from app.models.enums import MarketLatencyMode
from app.services.live_lab.market_data.base import LiveMarketDataAdapter
from app.services.live_lab.types import EventKind, MarketEvent


class ReplayMarketDataAdapter(LiveMarketDataAdapter):
    provider_id = "replay"

    def __init__(self, events: list[MarketEvent] | None = None, path: Path | None = None):
        self._queue: list[MarketEvent] = list(events or [])
        self._cursor = 0
        self._connected = False
        if path and path.exists():
            self._queue = self._load_file(path)

    @staticmethod
    def _load_file(path: Path) -> list[MarketEvent]:
        out: list[MarketEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            out.append(
                MarketEvent(
                    symbol=raw["symbol"],
                    kind=EventKind(raw.get("kind", "trade")),
                    exchange_ts=datetime.fromisoformat(raw["exchange_ts"]),
                    server_received_ts=datetime.fromisoformat(raw["server_received_ts"]),
                    latency_mode=MarketLatencyMode.HISTORICAL_REPLAY.value,
                    source="replay",
                    price=Decimal(str(raw["price"])) if raw.get("price") is not None else None,
                    size=raw.get("size"),
                    bid=Decimal(str(raw["bid"])) if raw.get("bid") is not None else None,
                    ask=Decimal(str(raw["ask"])) if raw.get("ask") is not None else None,
                    sequence=int(raw.get("sequence", len(out))),
                    payload=raw.get("payload") or {},
                )
            )
        out.sort(key=lambda e: (e.exchange_ts, e.sequence))
        return out

    @staticmethod
    def bars_to_trade_events(
        symbol: str,
        bars: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]],
        *,
        start_sequence: int = 0,
    ) -> list[MarketEvent]:
        """Convert closed 1m bars into trade events at bar close (conservative replay)."""
        events: list[MarketEvent] = []
        for i, (ts, o, h, low, c, vol) in enumerate(bars):
            recv = ts
            events.append(
                MarketEvent(
                    symbol=symbol,
                    kind=EventKind.CANDLE_CLOSE,
                    exchange_ts=ts,
                    server_received_ts=recv,
                    latency_mode=MarketLatencyMode.HISTORICAL_REPLAY.value,
                    source="replay",
                    price=c,
                    sequence=start_sequence + i + 10_000,
                    payload={"timeframe": "1m", "closed": True},
                )
            )
        return events

    def describe(self) -> dict:
        return {
            "provider": self.provider_id,
            "latency_mode": MarketLatencyMode.HISTORICAL_REPLAY.value,
            "licensing": "Deterministic replay — not exchange real-time.",
            "remaining_events": max(0, len(self._queue) - self._cursor),
        }

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def poll_events(self, limit: int = 500) -> list[MarketEvent]:
        if not self._connected:
            return []
        batch = self._queue[self._cursor : self._cursor + limit]
        self._cursor += len(batch)
        return batch

    def reset(self) -> None:
        self._cursor = 0