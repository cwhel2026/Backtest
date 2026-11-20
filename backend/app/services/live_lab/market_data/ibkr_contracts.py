"""IBKR futures contract resolution — read-only, extensible CME roots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# Root symbol → exchange (extend for FX futures on CME / GLOBEX as needed).
FUTURES_ROOT_EXCHANGE: dict[str, str] = {
    "MNQ": "CME",
    "MES": "CME",
    "MGC": "COMEX",
    "NQ": "CME",
    "ES": "CME",
    "GC": "COMEX",
    "MCL": "NYMEX",
    "6E": "GLOBEX",
    "6J": "GLOBEX",
}


@dataclass(frozen=True)
class ResolvedContract:
    root: str
    local_symbol: str
    exchange: str
    currency: str
    con_id: int | None
    last_trade_date: str | None
    latency_hint: str  # realtime | delayed | unknown


def exchange_for_root(root: str) -> str:
    return FUTURES_ROOT_EXCHANGE.get(root.upper(), "CME")


def format_contract_label(root: str, local_symbol: str | None, last_trade_date: str | None) -> str:
    if local_symbol:
        return local_symbol
    if last_trade_date:
        return f"{root.upper()} {last_trade_date}"
    return root.upper()


def resolve_front_month_via_ib(ib, root: str) -> ResolvedContract | None:
    """Qualify front future using ib_insync when gateway is available."""
    try:
        from ib_insync import Future
    except ImportError:
        return None
    exchange = exchange_for_root(root)
    template = Future(symbol=root.upper(), exchange=exchange, currency="USD")
    qualified = ib.qualifyContracts(template)
    if not qualified:
        return None
    c = sorted(qualified, key=lambda x: getattr(x, "lastTradeDateOrContractMonth", ""))[0]
    ltd = getattr(c, "lastTradeDateOrContractMonth", None)
    return ResolvedContract(
        root=root.upper(),
        local_symbol=str(getattr(c, "localSymbol", "") or ""),
        exchange=exchange,
        currency="USD",
        con_id=int(c.conId) if getattr(c, "conId", None) else None,
        last_trade_date=str(ltd) if ltd else None,
        latency_hint="unknown",
    )


def _as_resolved(obj: ResolvedContract | dict | None) -> ResolvedContract | None:
    if obj is None:
        return None
    if isinstance(obj, ResolvedContract):
        return obj
    if isinstance(obj, dict):
        return ResolvedContract(
            root=obj.get("root", ""),
            local_symbol=obj.get("local_symbol", ""),
            exchange=obj.get("exchange", "CME"),
            currency=obj.get("currency", "USD"),
            con_id=obj.get("con_id"),
            last_trade_date=obj.get("last_trade_date"),
            latency_hint=obj.get("latency_hint", "unknown"),
        )
    return None


def rollover_warning(previous: ResolvedContract | dict | None, current: ResolvedContract) -> str | None:
    prev = _as_resolved(previous)
    if not prev or not prev.last_trade_date or not current.last_trade_date:
        return None
    if prev.last_trade_date != current.last_trade_date:
        return f"Contract rolled from {prev.local_symbol or prev.last_trade_date} to {current.local_symbol or current.last_trade_date}"
    return None