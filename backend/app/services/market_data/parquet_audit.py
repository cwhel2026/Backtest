"""Parquet-native dataset audit without loading full OHLCV into memory."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pandas as pd

from app.backtest.bars import Bar
from app.services.market_data.ohlcv_parquet import dataset_dir, store_root
from app.services.market_data.quality import DatasetQualityReport, audit_bars


def iter_day_timestamps(dataset_id: UUID | str):
    folder = dataset_dir(dataset_id)
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.parquet")):
        try:
            df = pd.read_parquet(path, columns=["ts"])
        except (OSError, ValueError):
            continue
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        for ts in df["ts"]:
            yield ts.to_pydatetime()


def sample_bars_for_audit(
    dataset_id: UUID | str,
    *,
    max_bars: int = 60_000,
    timeframe: str = "1m",
) -> list[Bar]:
    """Stratified sample: head, tail, and spread across timeline."""
    folder = store_root() / str(dataset_id)
    paths = sorted(folder.glob("*.parquet"))
    if not paths:
        return []
    if len(paths) <= 3:
        take_paths = paths
    else:
        step = max(1, len(paths) // 40)
        take_paths = paths[::step]
        if paths[0] not in take_paths:
            take_paths = [paths[0]] + take_paths
        if paths[-1] not in take_paths:
            take_paths.append(paths[-1])

    bars: list[Bar] = []
    per_file_cap = max(500, max_bars // max(1, len(take_paths)))
    for path in take_paths:
        df = pd.read_parquet(path)
        if df.empty:
            continue
        df = df.head(per_file_cap)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        for _, row in df.iterrows():
            bars.append(
                Bar(
                    ts=row["ts"].to_pydatetime(),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=int(row["volume"]),
                )
            )
            if len(bars) >= max_bars:
                return bars
    return bars


def parquet_gap_summary(dataset_id: UUID | str, timeframe: str) -> dict:
    """Count gaps using timestamps only (bounded memory)."""
    prev: datetime | None = None
    gaps = 0
    dupes = 0
    count = 0
    mins = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}.get(timeframe, 1)
    expected = timedelta(minutes=mins)
    for ts in iter_day_timestamps(dataset_id):
        count += 1
        if prev:
            if ts == prev:
                dupes += 1
            elif ts > prev + expected * 2:
                gaps += 1
        prev = ts
    return {"bar_count_estimated": count, "timestamp_gaps": gaps, "duplicate_timestamps": dupes}


def audit_dataset_sampled(
    dataset_id: UUID | str,
    *,
    timeframe: str,
    symbol: str,
    max_bars: int = 60_000,
) -> DatasetQualityReport:
    bars = sample_bars_for_audit(dataset_id, max_bars=max_bars, timeframe=timeframe)
    summary = parquet_gap_summary(dataset_id, timeframe)
    base = audit_bars(bars, timeframe=timeframe, source="parquet_sample")
    base.warnings.append(
        f"Audit used sample of {len(bars)} bars; full series has ~{summary['bar_count_estimated']} timestamps"
    )
    if summary["duplicate_timestamps"]:
        base.warnings.append(f"Full scan found {summary['duplicate_timestamps']} duplicate timestamps")
    if summary["timestamp_gaps"]:
        base.warnings.append(f"Full timestamp scan found {summary['timestamp_gaps']} multi-interval gaps")
    base.bar_count = summary["bar_count_estimated"] or base.bar_count
    return base