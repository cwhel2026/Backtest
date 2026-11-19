"""Shared types for Live Strategy Lab market data and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    TRADE = "trade"
    QUOTE = "quote"
    STATUS = "status"
    HEARTBEAT = "heartbeat"
    CANDLE_CLOSE = "candle_close"


@dataclass(frozen=True)
class MarketEvent:
    symbol: str
    kind: EventKind
    exchange_ts: datetime
    server_received_ts: datetime
    latency_mode: str
    source: str
    price: Decimal | None = None
    size: int | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    contract_id: str | None = None
    trading_status: str | None = None
    quality_flags: list[str] = field(default_factory=list)
    sequence: int = 0
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def idempotency_key(self) -> str:
        return f"{self.source}:{self.symbol}:{self.kind}:{self.sequence}:{self.exchange_ts.isoformat()}"