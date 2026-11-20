"""IBKR tick replay from recorded JSONL — for CI and offline verification."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.core.config import get_settings
from app.models.enums import MarketLatencyMode
from app.services.live_lab.market_data.base import LiveMarketDataAdapter
from app.services.live_lab.market_data.ibkr_contracts import ResolvedContract, exchange_for_root
from app.services.live_lab.types import EventKind, MarketEvent


class IbkrFixtureAdapter(LiveMarketDataAdapter):
    provider_id = "ibkr_fixture"

    def __init__(self, symbols: list[str] | None = None, path: Path | None = None):
        self.symbols = [s.upper() for s in (symbols or ["MNQ", "MES", "MGC"])]
        settings = get_settings()
        fp = path or Path(settings.ibkr_fixture_path) if getattr(settings, "ibkr_fixture_path", "") else None
        if fp is None:
            fp = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "ibkr_sample_ticks.jsonl"
        self._path = fp
        self._queue: list[MarketEvent] = []
        self._cursor = 0
        self._connected = False
        self._seen: set[str] = set()
        self._contracts: dict[str, ResolvedContract] = {}
        if self._path.exists():
            self._queue = self._load()

    def _load(self) -> list[MarketEvent]:
        out: list[MarketEvent] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            sym = raw["symbol"].upper()
            if sym not in self.symbols:
                continue
            latency = raw.get("latency_mode") or MarketLatencyMode.DELAYED.value
            out.append(
                MarketEvent(
                    symbol=sym,
                    kind=EventKind(raw.get("kind", "trade")),
                    exchange_ts=datetime.fromisoformat(raw["exchange_ts"]),
                    server_received_ts=datetime.fromisoformat(raw.get("server_received_ts", raw["exchange_ts"])),
                    latency_mode=latency,
                    source="ibkr_fixture",
                    price=Decimal(str(raw["price"])) if raw.get("price") is not None else None,
                    bid=Decimal(str(raw["bid"])) if raw.get("bid") is not None else None,
                    ask=Decimal(str(raw["ask"])) if raw.get("ask") is not None else None,
                    sequence=int(raw.get("sequence", len(out))),
                    contract_id=raw.get("contract_id"),
                    payload=raw.get("payload") or {},
                )
            )
            if raw.get("contract_id"):
                self._contracts[sym] = ResolvedContract(
                    root=sym,
                    local_symbol=raw.get("contract_id", sym),
                    exchange=exchange_for_root(sym),
                    currency="USD",
                    con_id=None,
                    last_trade_date=raw.get("last_trade_date"),
                    latency_hint=latency,
                )
        out.sort(key=lambda e: (e.exchange_ts, e.sequence))
        return out

    def describe(self) -> dict:
        latency = MarketLatencyMode.DELAYED.value
        if self._queue:
            latency = self._queue[0].latency_mode
        return {
            "provider": self.provider_id,
            "latency_mode": latency,
            "verified": False,
            "configured": True,
            "note": "Recorded IBKR ticks — not live Gateway. Never labelled as exchange real-time.",
            "fixture_path": str(self._path),
            "contracts": {k: v.local_symbol for k, v in self._contracts.items()},
        }

    def verify_connectivity(self) -> dict:
        return {
            "ok": self._path.exists(),
            "reason": None if self._path.exists() else f"Missing fixture {self._path}",
            "live_gateway_required": "Set IBKR_HOST for production stream adapter",
        }

    def connect(self) -> None:
        if not self._queue and not self._path.exists():
            raise RuntimeError(f"IBKR fixture not found: {self._path}")
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def poll_events(self, limit: int = 500) -> list[MarketEvent]:
        if not self._connected:
            return []
        batch: list[MarketEvent] = []
        while self._cursor < len(self._queue) and len(batch) < limit:
            ev = self._queue[self._cursor]
            self._cursor += 1
            if ev.idempotency_key in self._seen:
                continue
            self._seen.add(ev.idempotency_key)
            batch.append(ev)
        return batch