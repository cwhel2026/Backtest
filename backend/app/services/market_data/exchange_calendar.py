"""Authoritative CME session calendar via exchange_calendars (holidays, schedules)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

SessionMode = Literal["RTH", "ETH", "ALL"]


@dataclass(frozen=True)
class RthWindow:
    start: time = time(8, 30)
    end: time = time(15, 0)


@dataclass(frozen=True)
class EthWindow:
    """Globex-style ETH: outside RTH but on a trading session day."""

    use_globex_session_date: bool = True


@dataclass(frozen=True)
class SessionPolicy:
    timezone: str = "America/Chicago"
    calendar_code: str = "CMES"
    rth: RthWindow = RthWindow()
    eth: EthWindow = EthWindow()
    allowed_modes: tuple[SessionMode, ...] = ("RTH",)


def _calendar(code: str):
    try:
        return xcals.get_calendar(code)
    except Exception:
        return xcals.get_calendar("CMES")


@lru_cache(maxsize=8)
def get_exchange_calendar(calendar_code: str = "CMES"):
    return _calendar(calendar_code)


def is_exchange_session_day(d: date, calendar_code: str = "CMES") -> bool:
    cal = get_exchange_calendar(calendar_code)
    try:
        return bool(cal.is_session(pd.Timestamp(d)))
    except Exception:
        return True


def early_close_local(d: date, calendar_code: str = "CMES", tz: str = "America/Chicago") -> time | None:
    """Return local early close time if the exchange publishes one for this date."""
    cal = get_exchange_calendar(calendar_code)
    try:
        idx = pd.DatetimeIndex([pd.Timestamp(d)])
        if hasattr(cal, "early_closes"):
            ec = cal.early_closes(idx)
            if ec is not None and len(ec) and ec[0] is not pd.NaT:
                utc = ec[0]
                if hasattr(utc, "to_pydatetime"):
                    utc = utc.to_pydatetime()
                if utc.tzinfo is None:
                    utc = utc.replace(tzinfo=ZoneInfo("UTC"))
                return utc.astimezone(ZoneInfo(tz)).time().replace(tzinfo=None)
    except Exception:
        pass
    return None


def _minutes_since_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def classify_bar_session(
    ts: datetime,
    policy: SessionPolicy,
) -> tuple[str, SessionMode | None]:
    """Return (session_key, mode) — mode None means bar is outside allowed modes."""
    zone = ZoneInfo(policy.timezone)
    local = ts.astimezone(zone) if ts.tzinfo else ts.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
    d = local.date()
    if not is_exchange_session_day(d, policy.calendar_code):
        return (f"closed:{d.isoformat()}", None)

    rth_end = early_close_local(d, policy.calendar_code, policy.timezone) or policy.rth.end
    mins = _minutes_since_midnight(local)
    rth_start_m = policy.rth.start.hour * 60 + policy.rth.start.minute
    rth_end_m = rth_end.hour * 60 + rth_end.minute

    in_rth = rth_start_m <= mins < rth_end_m
    if in_rth and "RTH" in policy.allowed_modes:
        return (f"rth:{d.isoformat()}", "RTH")

    if "ETH" in policy.allowed_modes or "ALL" in policy.allowed_modes:
        # Bars on session days outside RTH (Globex ETH segment)
        if "ETH" in policy.allowed_modes:
            return (f"eth:{d.isoformat()}", "ETH")
        if "ALL" in policy.allowed_modes:
            return (f"all:{d.isoformat()}", "ALL")

    return (f"off:{d.isoformat()}", None)


def session_policy_from_spec(spec: dict, instrument_trading_hours: dict | None = None) -> SessionPolicy:
    session = spec.get("session") or {}
    tz = str(session.get("timezone") or "America/Chicago")
    allowed = session.get("allowed") or ["RTH"]
    modes: list[SessionMode] = []
    for a in allowed:
        u = str(a).upper()
        if u in ("RTH", "ETH", "ALL"):
            modes.append(u)  # type: ignore[arg-type]
    if not modes:
        modes = ["RTH"]

    th = instrument_trading_hours or {}
    rth_cfg = th.get("rth") or {}
    for sess in th.get("sessions") or []:
        if str(sess.get("name", "")).upper() == "RTH":
            rth_cfg = sess
            break
    start_parts = str(rth_cfg.get("start", "08:30")).split(":")
    end_parts = str(rth_cfg.get("end", "15:15")).split(":")
    rth = RthWindow(
        start=time(int(start_parts[0]), int(start_parts[1])),
        end=time(int(end_parts[0]), int(end_parts[1])),
    )
    cal_code = str(th.get("exchange_calendar") or session.get("exchange_calendar") or "CMES")
    return SessionPolicy(timezone=tz, calendar_code=cal_code, rth=rth, allowed_modes=tuple(modes))


def expected_closure_between(
    prev: datetime,
    curr: datetime,
    policy: SessionPolicy,
) -> bool:
    """True if gap is plausibly session close, holiday, or maintenance — not missing data."""
    if curr <= prev:
        return False
    zone = ZoneInfo(policy.timezone)
    prev_l = prev.astimezone(zone)
    curr_l = curr.astimezone(zone)
    if prev_l.date() != curr_l.date():
        # Overnight between RTH close and next Globex open is expected
        if prev_l.hour * 60 + prev_l.minute >= policy.rth.end.hour * 60 + policy.rth.end.minute - 30:
            return True
        if not is_exchange_session_day(curr_l.date(), policy.calendar_code):
            return True
    minutes = int((curr - prev).total_seconds() // 60)
    if minutes <= 5:
        return False
    # Weekday gap on session day may be maintenance / close
    if minutes >= 60 and "ETH" not in policy.allowed_modes:
        return True
    return minutes > 16 * 60