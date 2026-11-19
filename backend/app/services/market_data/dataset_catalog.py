"""Dataset fingerprints, checksums, duplicate detection, versioning."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.enums import DatasetValidationStatus
from app.models.instrument import Instrument
from app.models.market_data import DataProvider, HistoricalDataset
from app.services.market_data.ohlcv_parquet import bar_count, checksum_sha256, coverage, has_store, write_bars

QualityClass = str  # ready | warning | blocked


def ingest_fingerprint(
    *,
    provider_slug: str,
    instrument_symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> str:
    payload = {
        "provider": provider_slug.lower(),
        "symbol": instrument_symbol.upper(),
        "timeframe": timeframe,
        "start": start.astimezone(UTC).isoformat(),
        "end": end.astimezone(UTC).isoformat(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]


def find_validated_duplicate(
    session: Session,
    *,
    fingerprint: str,
    instrument_id: uuid.UUID,
    timeframe: str,
) -> HistoricalDataset | None:
    q = select(HistoricalDataset).where(
        HistoricalDataset.instrument_id == instrument_id,
        HistoricalDataset.timeframe == timeframe,
    )
    for ds in session.execute(q).scalars().all():
        meta = ds.meta or {}
        if meta.get("ingest_fingerprint") != fingerprint:
            continue
        qc = (meta.get("quality_class") or "").lower()
        if qc in ("ready", "warning") and ds.validation_status == DatasetValidationStatus.VALIDATED:
            if has_store(ds.id) and bar_count(ds.id) > 0:
                return ds
    return None


def create_versioned_dataset(
    session: Session,
    *,
    provider_slug: str,
    instrument_id: uuid.UUID,
    timeframe: str,
    bars: list[tuple],
    meta: dict,
    fingerprint: str,
) -> HistoricalDataset:
    provider = session.execute(select(DataProvider).where(DataProvider.slug == provider_slug)).scalar_one_or_none()
    if not provider:
        raise ValueError(f"Unknown provider {provider_slug}")
    if not bars:
        raise ValueError("No bars to persist")

    inst = session.get(Instrument, instrument_id)
    version_tag = datetime.now(UTC).strftime("v%Y%m%d%H%M%S")
    dataset = HistoricalDataset(
        provider_id=provider.id,
        instrument_id=instrument_id,
        timeframe=timeframe,
        version_tag=version_tag,
        validation_status=DatasetValidationStatus.PENDING,
        meta={
            **meta,
            "ingest_fingerprint": fingerprint,
            "instrument_symbol": inst.symbol if inst else None,
            "synthetic": False,
            "store": "parquet",
        },
    )
    session.add(dataset)
    session.flush()
    write_bars(dataset.id, bars)
    dataset.row_count = bar_count(dataset.id)
    start, end = coverage(dataset.id)
    dataset.coverage_start = start
    dataset.coverage_end = end
    dataset.downloaded_at = datetime.now(UTC)
    try:
        dataset.content_checksum = checksum_sha256(dataset.id)
    except Exception:
        dataset.content_checksum = None
    session.flush()
    return dataset