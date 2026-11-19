"""Session keys for backtests and video strategies — calendar-aware RTH/ETH."""

from __future__ import annotations

from app.backtest.bars import Bar
from app.services.market_data.exchange_calendar import SessionPolicy, classify_bar_session, session_policy_from_spec


def session_keys_for_bars(
    bars: list[Bar],
    spec: dict | None = None,
    *,
    instrument_trading_hours: dict | None = None,
) -> list[str]:
    """One key per bar; RTH keys group bars that form completed session ranges for sweep logic."""
    policy = session_policy_from_spec(spec or {}, instrument_trading_hours)
    keys: list[str] = []
    for b in bars:
        key, _mode = classify_bar_session(b.ts, policy)
        keys.append(key)
    return keys


def session_keys_rth_calendar(
    bars: list[Bar],
    tz: str = "America/Chicago",
    instrument_trading_hours: dict | None = None,
) -> list[str]:
    """Backward-compatible RTH-only keys for DSL entry points."""
    spec = {"session": {"allowed": ["RTH"], "timezone": tz}}
    return session_keys_for_bars(bars, spec, instrument_trading_hours=instrument_trading_hours)