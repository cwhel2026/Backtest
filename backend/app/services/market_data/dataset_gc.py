"""Keep one OHLCV dataset per symbol/timeframe so search cannot fill Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.models.backtest import BacktestRun, OhlcvBar
from app.models.market_data import DataQualityReport, HistoricalDataset
from app.models.research import ResearchActivity, ResearchJob
from app.services.market_data.ohlcv_parquet import (
    bar_count,
    coverage,
    drop_dataset,
    retention_cutoff,
    trim_dataset,
    write_bars,
)


def has_stored_history(
    *,
    coverage_start: datetime | None,
    coverage_end: datetime | None,
    row_count: int,
    window_start: datetime,
    window_end: datetime | None = None,
    timeframe: str = "5m",
) -> bool:
    """True when the stored series already covers the requested lookback (tail may be stale)."""
    del window_end, timeframe
    if coverage_start is None or coverage_end is None or row_count < 80:
        return False
    start = _aware(coverage_start)
    w_start = _aware(window_start)
    if start > w_start + timedelta(days=2):
        return False
    return True


def should_reuse_dataset(
    *,
    coverage_start: datetime | None,
    coverage_end: datetime | None,
    row_count: int,
    window_start: datetime,
    window_end: datetime,
    timeframe: str = "5m",
) -> bool:
    return has_stored_history(
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        row_count=row_count,
        window_start=window_start,
        window_end=window_end,
        timeframe=timeframe,
    )


def tail_is_fresh(coverage_end: datetime | None, now: datetime, timeframe: str = "5m") -> bool:
    if coverage_end is None:
        return False
    max_lag = timedelta(minutes=45) if timeframe == "1m" else timedelta(hours=2)
    return _aware(now) - _aware(coverage_end) <= max_lag


def prune_orphan_datasets(session: Session) -> dict[str, int]:
    """Drop extra historical copies that no backtest points at."""
    referenced = {row[0] for row in session.execute(select(BacktestRun.dataset_id)).all() if row[0]}
    rows = session.execute(select(HistoricalDataset)).scalars().all()
    latest: dict[tuple, HistoricalDataset] = {}
    for ds in rows:
        key = (ds.instrument_id, ds.timeframe)
        prev = latest.get(key)
        ds_ts = ds.downloaded_at or ds.coverage_end or datetime.min.replace(tzinfo=UTC)
        prev_ts = (
            (prev.downloaded_at or prev.coverage_end or datetime.min.replace(tzinfo=UTC)) if prev else datetime.min.replace(tzinfo=UTC)
        )
        if prev is None or _aware(ds_ts) >= _aware(prev_ts):
            latest[key] = ds
    keep = {ds.id for ds in latest.values()} | referenced
    orphans = [ds for ds in rows if ds.id not in keep]
    bars_dropped = 0
    for ds in orphans:
        drop_dataset(ds.id)
        result = session.execute(delete(OhlcvBar).where(OhlcvBar.dataset_id == ds.id))
        bars_dropped += int(result.rowcount or 0)
        session.execute(delete(DataQualityReport).where(DataQualityReport.dataset_id == ds.id))
        session.delete(ds)
    return {"datasets_dropped": len(orphans), "bars_dropped": bars_dropped}


def prune_old_activity(session: Session, *, keep: int = 250) -> int:
    ids = session.execute(select(ResearchActivity.id).order_by(desc(ResearchActivity.created_at))).scalars().all()
    extra = ids[keep:]
    if not extra:
        return 0
    session.execute(delete(ResearchActivity).where(ResearchActivity.id.in_(extra)))
    return len(extra)


def prune_old_jobs(session: Session, *, keep: int = 20) -> int:
    from app.models.enums import ResearchJobStatus

    rows = session.execute(select(ResearchJob).order_by(desc(ResearchJob.created_at))).scalars().all()
    dropped = 0
    kept = 0
    for job in rows:
        if job.status in (ResearchJobStatus.RUNNING, ResearchJobStatus.QUEUED):
            continue
        if kept < keep:
            kept += 1
            continue
        session.execute(delete(ResearchActivity).where(ResearchActivity.job_id == job.id))
        session.delete(job)
        dropped += 1
    return dropped


def ohlcv_trim_cutoff(timeframe: str, now: datetime) -> datetime | None:
    return retention_cutoff(timeframe, now)


def trim_intraday_bars(session: Session, *, now: datetime | None = None) -> int:
    """Drop bars older than the search windows so live ticks cannot grow forever."""
    now = now or datetime.now(UTC)
    dropped = 0
    rows = session.execute(select(HistoricalDataset)).scalars().all()
    for ds in rows:
        cutoff = ohlcv_trim_cutoff(ds.timeframe, now)
        if cutoff is None:
            continue
        dropped += trim_dataset(ds.id, cutoff)
        result = session.execute(
            delete(OhlcvBar).where(OhlcvBar.dataset_id == ds.id, OhlcvBar.ts < cutoff)
        )
        dropped += int(result.rowcount or 0)
        stored = bar_count(ds.id)
        if stored:
            ds.row_count = stored
            start, end = coverage(ds.id)
            if start is not None:
                ds.coverage_start = start
            if end is not None:
                ds.coverage_end = end
        elif int(result.rowcount or 0):
            ds.row_count = max(0, int(ds.row_count or 0) - int(result.rowcount or 0))
            if ds.coverage_start is None or _aware(ds.coverage_start) < cutoff:
                ds.coverage_start = cutoff
    return dropped


def offload_postgres_ohlcv(session: Session) -> int:
    """Copy leftover ohlcv_bars rows into parquet, then delete them from Postgres."""
    moved = 0
    datasets = session.execute(select(HistoricalDataset)).scalars().all()
    for ds in datasets:
        rows = session.execute(
            select(OhlcvBar).where(OhlcvBar.dataset_id == ds.id).order_by(OhlcvBar.ts)
        ).scalars().all()
        if not rows:
            continue
        tuples = [
            (
                r.ts,
                Decimal(r.open),
                Decimal(r.high),
                Decimal(r.low),
                Decimal(r.close),
                int(r.volume or 0),
            )
            for r in rows
        ]
        try:
            write_bars(ds.id, tuples)
        except OSError:
            continue
        session.execute(delete(OhlcvBar).where(OhlcvBar.dataset_id == ds.id))
        ds.row_count = bar_count(ds.id)
        start, end = coverage(ds.id)
        if start is not None:
            ds.coverage_start = start
        if end is not None:
            ds.coverage_end = end
        meta = dict(ds.meta or {})
        meta["store"] = "parquet"
        ds.meta = meta
        moved += len(rows)
    return moved


def reclaim_search_disk(session: Session) -> dict[str, int]:
    stats = {"bars_offloaded": offload_postgres_ohlcv(session)}
    stats.update(prune_orphan_datasets(session))
    stats["bars_trimmed"] = trim_intraday_bars(session)
    stats["activities_dropped"] = prune_old_activity(session)
    stats["jobs_dropped"] = prune_old_jobs(session)
    return stats


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
