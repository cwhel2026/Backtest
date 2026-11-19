"""Persist OHLCV bar rows into a historical dataset."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.enums import DatasetValidationStatus
from app.models.market_data import DataProvider, HistoricalDataset
from app.services.market_data.ohlcv_parquet import bar_count, coverage, write_bars


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
        write_bars(dataset.id, deduped)
        dataset.row_count = bar_count(dataset.id)
        start, end = coverage(dataset.id)
        dataset.coverage_start = start
        dataset.coverage_end = end
    else:
        merge_bars_into_dataset(session, dataset, deduped)
        dataset.provider_id = provider.id
        dataset.version_tag = datetime.now(UTC).strftime("%Y%m%d%H%M%S")

    dataset.downloaded_at = datetime.now(UTC)
    dataset.validation_status = DatasetValidationStatus.VALIDATED
    from app.services.market_data.storage_backend import canonical_storage_uri

    uri = canonical_storage_uri(dataset.id)
    dataset.storage_uri = uri
    dataset.meta = {
        **(dataset.meta or {}),
        **meta,
        "synthetic": False,
        "duplicate_rows_skipped": dupes,
        "store": "parquet",
        "storage_uri": uri,
    }
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
    write_bars(dataset.id, incoming)
    _refresh_dataset_from_store(dataset)
    session.flush()
    return len(incoming)


def append_bars_to_dataset(
    session: Session,
    dataset: HistoricalDataset,
    bars: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]],
) -> int:
    """Insert bars newer than coverage_end. Returns count added."""
    if not bars:
        return 0
    incoming = bars_outside_coverage(dataset.coverage_start, dataset.coverage_end, bars)
    if not incoming:
        return 0
    write_bars(dataset.id, incoming)
    before = int(dataset.row_count or 0)
    _refresh_dataset_from_store(dataset)
    meta = dict(dataset.meta or {})
    meta["live_appended"] = int(meta.get("live_appended") or 0) + max(0, int(dataset.row_count or 0) - before)
    meta["store"] = "parquet"
    dataset.meta = meta
    session.flush()
    return max(0, int(dataset.row_count or 0) - before)


def _refresh_dataset_from_store(dataset: HistoricalDataset) -> None:
    dataset.row_count = bar_count(dataset.id)
    start, end = coverage(dataset.id)
    if start is not None:
        dataset.coverage_start = start
    if end is not None:
        dataset.coverage_end = end
    dataset.downloaded_at = datetime.now(UTC)