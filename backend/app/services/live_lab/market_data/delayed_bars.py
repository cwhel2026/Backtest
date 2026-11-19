"""Delayed bar refresh — uses existing Yahoo/Finz pull; never masquerades as realtime."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.enums import MarketLatencyMode
from app.services.live_lab.market_data.base import LiveMarketDataAdapter
from app.services.live_lab.types import EventKind, MarketEvent
from app.services.market_data.live_feed import refresh_live_bars_resilient


class DelayedBarsAdapter(LiveMarketDataAdapter):
    provider_id = "delayed_bars"

    def __init__(self, session: Session, symbols: list[str]):
        self._session = session
        self._symbols = symbols
        self._connected = False
        self._last_bar_ts: dict[str, datetime] = {}
        self._sequence = 0

    def describe(self) -> dict:
        return {
            "provider": self.provider_id,
            "latency_mode": MarketLatencyMode.DELAYED.value,
            "licensing": "Free/delayed vendors — not suitable for prop compliance without paid realtime.",
            "symbols": self._symbols,
        }

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def poll_events(self, limit: int = 500) -> list[MarketEvent]:
        if not self._connected:
            return []
        now = datetime.now(UTC)
        events: list[MarketEvent] = []
        for sym in self._symbols:
            try:
                refresh_live_bars_resilient(self._session, sym.upper(), "1m")
                self._session.flush()
            except Exception:
                continue
            from app.backtest.bars import load_bars
            from app.models.market_data import HistoricalDataset
            from sqlalchemy import desc, select
            from app.models.instrument import Instrument

            inst = self._session.execute(select(Instrument).where(Instrument.symbol == sym.upper())).scalar_one_or_none()
            if not inst:
                continue
            ds = self._session.execute(
                select(HistoricalDataset)
                .where(HistoricalDataset.instrument_id == inst.id, HistoricalDataset.timeframe == "1m")
                .order_by(desc(HistoricalDataset.downloaded_at))
                .limit(1)
            ).scalar_one_or_none()
            if not ds:
                continue
            bars = load_bars(self._session, ds.id)
            if not bars:
                continue
            last = bars[-1]
            prev = self._last_bar_ts.get(sym)
            if prev and last.ts <= prev:
                continue
            self._last_bar_ts[sym] = last.ts
            self._sequence += 1
            events.append(
                MarketEvent(
                    symbol=sym.upper(),
                    kind=EventKind.CANDLE_CLOSE,
                    exchange_ts=last.ts,
                    server_received_ts=now,
                    latency_mode=MarketLatencyMode.DELAYED.value,
                    source="delayed_bars",
                    price=last.close,
                    size=last.volume,
                    sequence=self._sequence,
                    payload={
                        "timeframe": "1m",
                        "open": str(last.open),
                        "high": str(last.high),
                        "low": str(last.low),
                        "close": str(last.close),
                        "volume": last.volume,
                    },
                )
            )
            if len(events) >= limit:
                break
        return events