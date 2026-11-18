"""Persist OHLCV bar rows into a historical dataset."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.backtest import OhlcvBar
from app.models.enums import DatasetValidationStatus
from app.models.market_data import DataProvider, HistoricalDataset


def persist_bars_to_dataset(
    session: Session,
    *,
    provider_slug: str,
    instrument_id: uuid.UUID,
    timeframe: str,
    bars: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]],
    meta: dict,
) -> HistoricalDataset:
    if not bars:
        raise ValueError("No bars to persist")

    provider = session.execute(select(DataProvider).where(DataProvider.slug == provider_slug)).scalar_one_or_none()
    if not provider:
        raise ValueError(f"Unknown provider {provider_slug}")

    seen: set[datetime] = set()
    deduped: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]] = []
    dupes = 0
    for row in sorted(bars, key=lambda x: x[0]):
        ts = row[0].astimezone(UTC)
        if ts in seen:
            dupes += 1
            continue
        seen.add(ts)
        deduped.append((ts, row[1], row[2], row[3], row[4], row[5]))

    if not deduped:
        raise ValueError("No bars after deduplication")

    existing = session.execute(
        select(HistoricalDataset)
        .where(HistoricalDataset.instrument_id == instrument_id, HistoricalDataset.timeframe == timeframe)
        .order_by(desc(HistoricalDataset.downloaded_at))
        .limit(1)
    ).scalar_one_or_none()
    dataset = existing or HistoricalDataset(
        provider_id=provider.id,
        instrument_id=instrument_id,
        timeframe=timeframe,
        version_tag=datetime.now(UTC).strftime("%Y%m%d%H%M%S"),
        validation_status=DatasetValidationStatus.PENDING,
        meta={**meta, "synthetic": False},
    )
    if existing is None:
        session.add(dataset)
        session.flush()
        _insert_ohlcv_chunks(session, dataset.id, deduped)
        dataset.row_count = len(deduped)
        dataset.coverage_start = deduped[0][0]
        dataset.coverage_end = deduped[-1][0]
    else:
        merge_bars_into_dataset(session, dataset, deduped)
        dataset.provider_id = provider.id
        dataset.version_tag = datetime.now(UTC).strftime("%Y%m%d%H%M%S")

    dataset.downloaded_at = datetime.now(UTC)
    dataset.validation_status = DatasetValidationStatus.VALIDATED
    dataset.meta = {**(dataset.meta or {}), **meta, "synthetic": False, "duplicate_rows_skipped": dupes}
    session.flush()
    return dataset


def bars_outside_coverage(
    coverage_start: datetime | None,
    coverage_end: datetime | None,
    bars: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]],
) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]]:
    """Keep only bars strictly before coverage_start or after coverage_end."""
    out: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]] = []
    seen: set[datetime] = set()
    start = coverage_start.astimezone(UTC) if coverage_start and coverage_start.tzinfo else coverage_start
    end = coverage_end.astimezone(UTC) if coverage_end and coverage_end.tzinfo else coverage_end
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    for row in sorted(bars, key=lambda x: x[0]):
        ts = row[0].astimezone(UTC) if row[0].tzinfo else row[0].replace(tzinfo=UTC)
        if ts in seen:
            continue
        seen.add(ts)
        if start is not None and end is not None and start <= ts <= end:
            continue
        out.append((ts, row[1], row[2], row[3], row[4], row[5]))
    return out


def merge_bars_into_dataset(
    session: Session,
    dataset: HistoricalDataset,
    bars: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]],
) -> int:
    """Insert bars the stored series does not already cover. Never deletes existing rows."""
    incoming = bars_outside_coverage(dataset.coverage_start, dataset.coverage_end, bars)
    if not incoming:
        return 0
    _insert_ohlcv_chunks(session, dataset.id, incoming)
    dataset.row_count = int(dataset.row_count or 0) + len(incoming)
    first, last = incoming[0][0], incoming[-1][0]
    if dataset.coverage_start is None or first < dataset.coverage_start:
        dataset.coverage_start = first
    if dataset.coverage_end is None or last > dataset.coverage_end:
        dataset.coverage_end = last
    dataset.downloaded_at = datetime.now(UTC)
    session.flush()
    return len(incoming)


def _insert_ohlcv_chunks(
    session: Session,
    dataset_id: uuid.UUID,
    rows: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]],
    *,
    chunk_size: int = 1500,
) -> None:
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        session.add_all(
            [
                OhlcvBar(
                    dataset_id=dataset_id,
                    ts=ts,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
                for ts, open_, high, low, close, volume in chunk
            ]
        )
        session.flush()


def append_bars_to_dataset(
    session: Session,
    dataset: HistoricalDataset,
    bars: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]],
) -> int:
    """Insert bars newer than coverage_end. Returns count added."""
    if not bars:
        return 0
    cutoff = dataset.coverage_end
    added: list[OhlcvBar] = []
    for ts, o, h, l, c, v in sorted(bars, key=lambda x: x[0]):
        ts_u = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
        if cutoff is not None and ts_u <= cutoff:
            continue
        added.append(
            OhlcvBar(dataset_id=dataset.id, ts=ts_u, open=o, high=h, low=l, close=c, volume=v)
        )
    if not added:
        return 0
    session.add_all(added)
    dataset.row_count = int(dataset.row_count or 0) + len(added)
    dataset.coverage_end = added[-1].ts
    if dataset.coverage_start is None:
        dataset.coverage_start = added[0].ts
    dataset.downloaded_at = datetime.now(UTC)
    meta = dict(dataset.meta or {})
    meta["live_appended"] = int(meta.get("live_appended") or 0) + len(added)
    dataset.meta = meta
    session.flush()
    return len(added)