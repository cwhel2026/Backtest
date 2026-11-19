"""Daily parquet files for OHLCV. Postgres keeps dataset metadata, not bar rows.

Railway Postgres filled up inserting 1m bars. Search/paper now read these files.
Rollover = one file per UTC day; GC unlinks days older than the search window.
"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterator
from uuid import UUID

import pandas as pd

from app.core.config import get_settings

BarTuple = tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]

_STORE_OVERRIDE: Path | None = None


def set_store_dir(path: Path | str | None) -> None:
    global _STORE_OVERRIDE
    _STORE_OVERRIDE = Path(path) if path is not None else None


def store_root() -> Path:
    if _STORE_OVERRIDE is not None:
        root = _STORE_OVERRIDE
    else:
        raw = (get_settings().ohlcv_store_dir or "data/ohlcv").strip()
        root = Path(raw)
        if not root.is_absolute():
            root = Path.cwd() / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def dataset_dir(dataset_id: UUID | str) -> Path:
    path = store_root() / str(dataset_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def has_store(dataset_id: UUID | str) -> bool:
    path = store_root() / str(dataset_id)
    return path.is_dir() and any(path.glob("*.parquet"))


@contextmanager
def _dataset_lock(dataset_id: UUID | str) -> Iterator[None]:
    lock_path = dataset_dir(dataset_id) / ".lock"
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_bars(dataset_id: UUID | str, bars: list[BarTuple]) -> int:
    """Merge bars into per-day parquet files. Returns count of timestamps now stored."""
    if not bars:
        return 0
    incoming = _frame(bars)
    if incoming.empty:
        return 0
    with _dataset_lock(dataset_id):
        folder = dataset_dir(dataset_id)
        for day_key, chunk in incoming.groupby(incoming["ts"].dt.date, sort=True):
            path = folder / f"{day_key.isoformat()}.parquet"
            if path.exists():
                existing = pd.read_parquet(path)
                existing["ts"] = pd.to_datetime(existing["ts"], utc=True)
                chunk = pd.concat([existing, chunk], ignore_index=True)
            chunk = chunk.drop_duplicates(subset=["ts"], keep="last").sort_values("ts")
            chunk.to_parquet(path, index=False)
        return bar_count(dataset_id)


def read_bars(
    dataset_id: UUID | str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[BarTuple]:
    folder = store_root() / str(dataset_id)
    if not folder.is_dir():
        return []
    frames: list[pd.DataFrame] = []
    start_d = _as_date(start) if start else None
    end_d = _as_date(end) if end else None
    for path in sorted(folder.glob("*.parquet")):
        day = _filename_day(path)
        if day is None:
            continue
        if start_d and day < start_d:
            continue
        if end_d and day > end_d:
            continue
        df = pd.read_parquet(path)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        frames.append(df)
    if not frames:
        return []
    out = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["ts"]).sort_values("ts")
    if start is not None:
        out = out[out["ts"] >= pd.Timestamp(start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC))]
    if end is not None:
        out = out[out["ts"] <= pd.Timestamp(end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC))]
    return _to_tuples(out)


def bar_count(dataset_id: UUID | str) -> int:
    folder = store_root() / str(dataset_id)
    if not folder.is_dir():
        return 0
    total = 0
    for path in folder.glob("*.parquet"):
        try:
            total += int(pd.read_parquet(path, columns=["ts"]).shape[0])
        except (OSError, ValueError):
            continue
    return total


def coverage(dataset_id: UUID | str) -> tuple[datetime | None, datetime | None]:
    rows = read_bars(dataset_id)
    if not rows:
        return None, None
    return rows[0][0], rows[-1][0]


def drop_dataset(dataset_id: UUID | str) -> int:
    folder = store_root() / str(dataset_id)
    if not folder.exists():
        return 0
    removed = 0
    with _dataset_lock(dataset_id):
        for path in folder.glob("*"):
            if path.is_file():
                path.unlink()
                removed += 1
    try:
        folder.rmdir()
    except OSError:
        pass
    return removed


def trim_dataset(dataset_id: UUID | str, cutoff: datetime) -> int:
    """Drop whole day files before cutoff; rewrite the cutoff day without older bars."""
    folder = store_root() / str(dataset_id)
    if not folder.is_dir():
        return 0
    cutoff_u = cutoff.astimezone(UTC) if cutoff.tzinfo else cutoff.replace(tzinfo=UTC)
    cutoff_day = cutoff_u.date()
    dropped = 0
    with _dataset_lock(dataset_id):
        for path in list(folder.glob("*.parquet")):
            day = _filename_day(path)
            if day is None:
                continue
            if day < cutoff_day:
                try:
                    n = int(pd.read_parquet(path, columns=["ts"]).shape[0])
                except (OSError, ValueError):
                    n = 0
                path.unlink(missing_ok=True)
                dropped += n
            elif day == cutoff_day:
                df = pd.read_parquet(path)
                df["ts"] = pd.to_datetime(df["ts"], utc=True)
                keep = df[df["ts"] >= pd.Timestamp(cutoff_u)]
                dropped += int(len(df) - len(keep))
                if keep.empty:
                    path.unlink(missing_ok=True)
                else:
                    keep.to_parquet(path, index=False)
    return dropped


def _frame(bars: list[BarTuple]) -> pd.DataFrame:
    rows = []
    for ts, o, h, low, c, v in bars:
        ts_u = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
        rows.append(
            {
                "ts": ts_u,
                "open": float(o),
                "high": float(h),
                "low": float(low),
                "close": float(c),
                "volume": int(v or 0),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts")


def _to_tuples(df: pd.DataFrame) -> list[BarTuple]:
    out: list[BarTuple] = []
    for row in df.itertuples(index=False):
        ts = row.ts.to_pydatetime() if hasattr(row.ts, "to_pydatetime") else row.ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)
        out.append(
            (
                ts,
                Decimal(str(round(float(row.open), 8))),
                Decimal(str(round(float(row.high), 8))),
                Decimal(str(round(float(row.low), 8))),
                Decimal(str(round(float(row.close), 8))),
                int(row.volume or 0),
            )
        )
    return out


def _filename_day(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def _as_date(value: datetime | pd.Timestamp | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.date()
    raise TypeError(f"Cannot date-cast {type(value)}")


def checksum_sha256(dataset_id: UUID | str) -> str:
    """Content hash over sorted parquet day files (metadata only — not mutating data)."""
    import hashlib

    folder = store_root() / str(dataset_id)
    if not folder.is_dir():
        return ""
    h = hashlib.sha256()
    for path in sorted(folder.glob("*.parquet")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def retention_cutoff(timeframe: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(UTC)
    tf = (timeframe or "5m").strip().lower()
    if tf in ("1m", "1min", "1"):
        return now - timedelta(days=35)
    if tf in ("5m", "15m"):
        return now - timedelta(days=70)
    return None
