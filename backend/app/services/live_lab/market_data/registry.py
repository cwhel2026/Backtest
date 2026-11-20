from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.instruments import PRIMARY_RESEARCH_SYMBOLS
from app.services.live_lab.market_data.base import LiveMarketDataAdapter
from app.services.live_lab.market_data.delayed_bars import DelayedBarsAdapter
from app.services.live_lab.market_data.replay import ReplayMarketDataAdapter
from app.services.live_lab.market_data.ibkr_fixture import IbkrFixtureAdapter
from app.services.live_lab.market_data.ibkr_stream import IbkrStreamAdapter
from app.services.live_lab.market_data.stubs import CmeWebSocketAdapter, DatabentoLiveAdapter, IbkrTwsAdapter


def get_market_data_adapter(session: Session, replay_events=None) -> LiveMarketDataAdapter:
    settings = get_settings()
    provider = (getattr(settings, "live_lab_provider", None) or "replay").lower()
    symbols = [
        s.strip().upper()
        for s in (getattr(settings, "live_lab_symbols", None) or ",".join(PRIMARY_RESEARCH_SYMBOLS)).split(",")
        if s.strip()
    ]
    if provider == "replay":
        path = getattr(settings, "live_lab_replay_path", "") or ""
        return ReplayMarketDataAdapter(replay_events, Path(path) if path else None)
    if provider == "delayed_bars":
        return DelayedBarsAdapter(session, symbols)
    if provider == "databento_live":
        return DatabentoLiveAdapter()
    if provider == "ibkr_fixture":
        return IbkrFixtureAdapter(symbols)
    if provider in ("ibkr_tws", "ibkr_stream"):
        if provider == "ibkr_stream" or settings.ibkr_configured:
            return IbkrStreamAdapter(symbols)
        return IbkrTwsAdapter()
    if provider == "cme_websocket":
        return CmeWebSocketAdapter()
    return ReplayMarketDataAdapter(replay_events)