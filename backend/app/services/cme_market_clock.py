"""CME Globex session clock (CMES calendar) — independent of live feed provider."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.services.market_data.exchange_calendar import get_exchange_calendar, is_exchange_session_day

CHICAGO = ZoneInfo("America/Chicago")


def cme_futures_market_status(*, now: datetime | None = None) -> dict:
    """
    Return whether CMES recognizes today as a trading session and coarse session label.
    Saturday/Sunday/holidays: session_day=False (historical research still allowed).
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local = now.astimezone(CHICAGO)
    session_day = is_exchange_session_day(local.date(), "CMES")
    cal = get_exchange_calendar("CMES")
    open_now = False
    if session_day:
        try:
            import pandas as pd

            ts = pd.Timestamp(now)
            if hasattr(cal, "is_open_on_minute"):
                open_now = bool(cal.is_open_on_minute(ts))
        except Exception:
            open_now = False

    if not session_day:
        label = "closed_weekend_or_holiday"
        headline = "CME futures: no trading session today (CMES calendar)"
    elif open_now:
        label = "session_open"
        headline = "CME futures: session open (CMES minute calendar)"
    else:
        label = "session_closed"
        headline = "CME futures: trading day but market closed at this time"

    return {
        "exchange": "CMES",
        "timezone": "America/Chicago",
        "local_time": local.isoformat(),
        "utc_time": now.isoformat(),
        "session_day": session_day,
        "market_open_now": open_now,
        "status": label,
        "headline": headline,
        "note": "Historical backtest, replay, and paper on stored bars work regardless of this clock.",
    }