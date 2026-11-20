"""IBKR market data stream adapter (ib-insync). Unverified without gateway credentials."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.config import get_settings
from app.models.enums import MarketLatencyMode
from app.services.live_lab.market_data.base import LiveMarketDataAdapter
from app.services.live_lab.market_data.ibkr_contracts import resolve_front_month_via_ib, rollover_warning
from app.services.live_lab.types import EventKind, MarketEvent

_PRIMARY = {"MNQ", "MES", "MGC"}


class IbkrStreamAdapter(LiveMarketDataAdapter):
    provider_id = "ibkr_stream"

    def __init__(self, symbols: list[str] | None = None):
        self.symbols = [s.upper() for s in (symbols or list(_PRIMARY))]
        self._connected = False
        self._verified = False
        self._ib = None
        self._ticker_map: dict = {}
        self._sequence = 0
        self._last_keys: set[str] = set()
        self._contracts: dict = {}
        self._md_type: dict[str, int] = {}

    def describe(self) -> dict:
        s = get_settings()
        return {
            "provider": self.provider_id,
            "latency_mode": self._latency_label(),
            "documentation": "https://interactivebrokers.github.io/tws-api/md_request.html",
            "configured": s.ibkr_configured,
            "verified": self._verified,
            "note": "Requires reachable IB Gateway and market data subscription. Not tested in CI.",
        }

    def _latency_label(self) -> str:
        if not self._verified:
            return MarketLatencyMode.SYNTHETIC.value
        if any(t == 1 for t in self._md_type.values()):
            return MarketLatencyMode.REALTIME.value
        if any(t == 3 for t in self._md_type.values()):
            return MarketLatencyMode.DELAYED.value
        return MarketLatencyMode.DELAYED.value

    def verify_connectivity(self) -> dict:
        settings = get_settings()
        if not settings.ibkr_configured:
            return {"ok": False, "reason": "IBKR_HOST not configured"}
        try:
            from ib_insync import IB
        except ImportError:
            return {"ok": False, "reason": "ib-insync not installed"}
        ib = IB()
        try:
            ib.connect(settings.ibkr_host, int(settings.ibkr_port), clientId=int(settings.ibkr_client_id) + 50, readonly=True)
            self._verified = ib.isConnected()
            ib.disconnect()
            return {"ok": self._verified, "host": settings.ibkr_host, "port": settings.ibkr_port}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    def connect(self) -> None:
        settings = get_settings()
        if not settings.ibkr_configured:
            raise RuntimeError("IBKR not configured")
        from ib_insync import IB, Future

        self._ib = IB()
        self._ib.connect(settings.ibkr_host, int(settings.ibkr_port), clientId=int(settings.ibkr_client_id) + 50, readonly=True)
        self._connected = self._ib.isConnected()
        self._verified = self._connected
        for sym in self.symbols:
            resolved = resolve_front_month_via_ib(self._ib, sym)
            if not resolved or not resolved.con_id:
                continue
            prev = self._contracts.get(sym)
            warn = rollover_warning(prev, resolved) if prev else None
            if warn:
                self._contracts[sym] = {**resolved.__dict__, "rollover_warning": warn}
            else:
                self._contracts[sym] = resolved.__dict__
            from ib_insync import Future

            c = Future(conId=resolved.con_id, exchange=resolved.exchange)
            qualified = self._ib.qualifyContracts(c)
            if not qualified:
                continue
            c = qualified[0]
            ticker = self._ib.reqMktData(c, "", False, False)
            self._ticker_map[sym] = ticker
            mdt = getattr(ticker, "marketDataType", None) or 3
            self._md_type[sym] = int(mdt)

    def disconnect(self) -> None:
        if self._ib:
            for sym in list(self._ticker_map):
                try:
                    self._ib.cancelMktData(self._ticker_map[sym].contract)
                except Exception:
                    pass
            self._ib.disconnect()
        self._connected = False
        self._ticker_map = {}

    def poll_events(self, limit: int = 500) -> list[MarketEvent]:
        if not self._connected or not self._ib:
            return []
        now = datetime.now(UTC)
        self._ib.sleep(0)
        events: list[MarketEvent] = []
        for sym, ticker in self._ticker_map.items():
            last = getattr(ticker, "last", None)
            bid = getattr(ticker, "bid", None)
            ask = getattr(ticker, "ask", None)
            if last is None and bid is None and ask is None:
                continue
            self._sequence += 1
            ev = MarketEvent(
                symbol=sym,
                kind=EventKind.QUOTE if bid is not None or ask is not None else EventKind.TRADE,
                exchange_ts=now,
                server_received_ts=now,
                latency_mode=self._latency_label(),
                source="ibkr_stream",
                contract_id=(self._contracts.get(sym) or {}).get("local_symbol"),
                price=Decimal(str(last)) if last not in (None, 0) else None,
                bid=Decimal(str(bid)) if bid not in (None, 0) else None,
                ask=Decimal(str(ask)) if ask not in (None, 0) else None,
                bid_size=getattr(ticker, "bidSize", None),
                ask_size=getattr(ticker, "askSize", None),
                sequence=self._sequence,
            )
            if ev.idempotency_key in self._last_keys:
                continue
            self._last_keys.add(ev.idempotency_key)
            events.append(ev)
            if len(events) >= limit:
                break
        return events