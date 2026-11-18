"""Historical bars from a reachable IB Gateway / TWS (same network as the worker)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.bars import Bar
from app.core.config import get_settings

# CME micro/mini front month — extend mapping as needed
_IBKR_SYMBOL = {
    "MNQ": "MNQ",
    "NQ": "NQ",
    "MES": "MES",
    "ES": "ES",
    "MCL": "MCL",
    "CL": "CL",
}


def fetch_ibkr_bars(
    instrument_symbol: str,
    *,
    start: datetime,
    end: datetime,
    bar_size: str = "5 mins",
    use_rth: bool = True,
) -> list[Bar]:
    settings = get_settings()
    if not settings.ibkr_configured:
        raise ValueError("IBKR_HOST not configured — point worker at your IB Gateway.")
    try:
        from ib_insync import IB, Future
    except ImportError as exc:
        raise ValueError("ib-insync not installed on worker") from exc

    root = _IBKR_SYMBOL.get(instrument_symbol.upper(), instrument_symbol.upper())
    ib = IB()
    ib.connect(settings.ibkr_host, int(settings.ibkr_port), clientId=int(settings.ibkr_client_id), readonly=True)
    try:
        contract = Future(symbol=root, exchange="CME", currency="USD")
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            raise ValueError(f"IBKR could not qualify contract for {instrument_symbol}")
        contract = qualified[0]
        duration = max(1, (end - start).days)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end,
            durationStr=f"{duration} D",
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=use_rth,
            formatDate=1,
        )
        out: list[Bar] = []
        for b in bars:
            if b.date < start:
                continue
            ts = b.date
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            else:
                ts = ts.astimezone(UTC)
            out.append(
                Bar(
                    ts=ts,
                    open=Decimal(str(b.open)),
                    high=Decimal(str(b.high)),
                    low=Decimal(str(b.low)),
                    close=Decimal(str(b.close)),
                    volume=int(b.volume or 0),
                )
            )
        if not out:
            raise ValueError(f"IBKR returned no bars for {instrument_symbol}")
        return out
    finally:
        ib.disconnect()


def fetch_ibkr_quote(instrument_symbol: str) -> dict:
    """Last trade from IB Gateway market data (requires a live/paper market-data subscription)."""
    settings = get_settings()
    if not settings.ibkr_configured:
        raise ValueError("IBKR_HOST not configured — point worker at your IB Gateway.")
    try:
        from ib_insync import IB, Future
    except ImportError as exc:
        raise ValueError("ib-insync not installed on worker") from exc

    root = _IBKR_SYMBOL.get(instrument_symbol.upper(), instrument_symbol.upper())
    ib = IB()
    ib.connect(
        settings.ibkr_host,
        int(settings.ibkr_port),
        clientId=int(settings.ibkr_client_id) + 7,
        readonly=True,
    )
    try:
        contract = Future(symbol=root, exchange="CME", currency="USD")
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            raise ValueError(f"IBKR could not qualify contract for {instrument_symbol}")
        ticker = ib.reqMktData(qualified[0], "", False, False)
        ib.sleep(1.2)
        last = ticker.marketPrice()
        if last is None or last != last:  # NaN
            last = ticker.last or ticker.close
        if last is None or last != last:
            raise ValueError(f"IBKR returned no last price for {instrument_symbol}")
        return {
            "symbol": root,
            "last": float(last),
            "bid": float(ticker.bid) if ticker.bid is not None and ticker.bid == ticker.bid else None,
            "ask": float(ticker.ask) if ticker.ask is not None and ticker.ask == ticker.ask else None,
            "ts": datetime.now(UTC),
            "source": "ibkr",
        }
    finally:
        ib.disconnect()


def bar_size_for_timeframe(timeframe: str) -> str:
    return {"1m": "1 min", "5m": "5 mins", "15m": "15 mins", "1h": "1 hour"}.get(timeframe, "5 mins")