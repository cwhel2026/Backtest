"""Persist OHLCV bar rows into a historical dataset."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

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

    from sqlalchemy import select

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

    dataset = HistoricalDataset(
        provider_id=provider.id,
        instrument_id=instrument_id,
        timeframe=timeframe,
        version_tag=datetime.now(UTC).strftime("%Y%m%d%H%M%S"),
        validation_status=DatasetValidationStatus.PENDING,
        meta={**meta, "synthetic": False},
    )
    session.add(dataset)
    session.flush()

    ohlcv_rows = [
        OhlcvBar(
            dataset_id=dataset.id,
            ts=ts,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        for ts, open_, high, low, close, volume in deduped
    ]
    session.add_all(ohlcv_rows)

    dataset.row_count = len(ohlcv_rows)
    dataset.coverage_start = deduped[0][0]
    dataset.coverage_end = deduped[-1][0]
    dataset.downloaded_at = datetime.now(UTC)
    dataset.validation_status = DatasetValidationStatus.VALIDATED
    dataset.meta["duplicate_rows_skipped"] = dupes
    session.flush()
    return dataset


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