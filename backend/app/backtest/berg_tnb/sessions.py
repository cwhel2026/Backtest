"""PDF-defined session profiles (GMT/UTC) — separate from CME RTH research mode."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.backtest.bars import Bar

UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class MeasurementWindow:
    name: str
    start: time
    end: time
    """End is exclusive when end < start uses next calendar day (not needed for PDF presets)."""


@dataclass(frozen=True)
class SessionProfile:
    key: str
    label: str
    asia_open_gmt: time
    london_open_gmt: time
    new_york_open_gmt: time
    measurement_windows: dict[str, MeasurementWindow]
    dst_note: str = (
        "Session opens are fixed at GMT/UTC wall times. "
        "No DST shift is applied to PDF markers (interpretation — PDF silent on DST)."
    )


PDF_INDICES = SessionProfile(
    key="pdf_indices",
    label="PDF indices (GMT)",
    asia_open_gmt=time(0, 0),
    london_open_gmt=time(8, 0),
    new_york_open_gmt=time(14, 30),
    measurement_windows={
        "london_setup": MeasurementWindow("london_setup", time(0, 0), time(8, 0)),
        "new_york_setup": MeasurementWindow("new_york_setup", time(8, 0), time(13, 0)),
    },
)

PDF_FOREX = SessionProfile(
    key="pdf_forex",
    label="PDF forex (GMT)",
    asia_open_gmt=time(0, 0),
    london_open_gmt=time(8, 0),
    new_york_open_gmt=time(13, 0),
    measurement_windows={
        "london_setup": MeasurementWindow("london_setup", time(0, 0), time(8, 0)),
        "new_york_setup": MeasurementWindow("new_york_setup", time(8, 0), time(13, 0)),
    },
)

CME_FUTURES_RESEARCH = SessionProfile(
    key="cme_futures_research",
    label="CME futures (Chicago RTH research — not PDF equivalent)",
    asia_open_gmt=time(0, 0),
    london_open_gmt=time(14, 30),
    new_york_open_gmt=time(14, 30),
    measurement_windows={
        "london_setup": MeasurementWindow("london_setup", time(14, 30), time(20, 45)),
        "new_york_setup": MeasurementWindow("new_york_setup", time(20, 45), time(21, 0)),
    },
    dst_note="Approximate CME equity index RTH mapping for labelled experiments only.",
)

PROFILES: dict[str, SessionProfile] = {
    p.key: p for p in (PDF_INDICES, PDF_FOREX, CME_FUTURES_RESEARCH)
}


def get_profile(key: str) -> SessionProfile:
    if key not in PROFILES:
        raise ValueError(f"Unknown session profile {key!r}; choose from {sorted(PROFILES)}")
    return PROFILES[key]


def _utc_time(dt: datetime) -> time:
    u = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return u.timetz().replace(tzinfo=None)


def _window_bounds(d: date, w: MeasurementWindow) -> tuple[datetime, datetime]:
    start = datetime.combine(d, w.start, UTC)
    end = datetime.combine(d, w.end, UTC)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def completed_measurement_for_bar(
    bar_ts: datetime,
    profile: SessionProfile,
    setup_preset: str,
) -> tuple[str, datetime, datetime] | None:
    """If bar_ts is strictly after a full measurement window, return id and bounds."""
    w = profile.measurement_windows.get(setup_preset)
    if not w:
        return None
    u = bar_ts.astimezone(UTC) if bar_ts.tzinfo else bar_ts.replace(tzinfo=UTC)
    d = u.date()
    for day_off in (0, -1):
        day = d if day_off == 0 else d - timedelta(days=1)
        start, end = _window_bounds(day, w)
        if u >= end:
            sid = f"{profile.key}:{setup_preset}:{day.isoformat()}"
            return sid, start, end
    return None


def aggregate_session_extremes(
    bars: list[Bar],
    start: datetime,
    end: datetime,
) -> tuple[Decimal, Decimal] | None:
    chunk = [b for b in bars if start <= (b.ts if b.ts.tzinfo else b.ts.replace(tzinfo=UTC)) < end]
    if not chunk:
        return None
    return max(b.high for b in chunk), min(b.low for b in chunk)