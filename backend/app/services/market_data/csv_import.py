"""Import user-provided OHLCV CSV into a historical dataset."""

import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.backtest import OhlcvBar
from app.models.enums import DatasetValidationStatus
from app.models.market_data import DataProvider, HistoricalDataset


def parse_timestamp(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def import_csv_bars(
    session: Session,
    *,
    provider_slug: str,
    instrument_id: uuid.UUID,
    timeframe: str,
    label: str,
    csv_text: str,
) -> HistoricalDataset:
    provider = session.execute(select(DataProvider).where(DataProvider.slug == provider_slug)).scalar_one_or_none()
    if not provider:
        raise ValueError(f"Unknown provider {provider_slug}")

    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"timestamp", "open", "high", "low", "close"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("CSV must include columns: timestamp, open, high, low, close (volume optional)")

    dataset = HistoricalDataset(
        provider_id=provider.id,
        instrument_id=instrument_id,
        timeframe=timeframe,
        version_tag=datetime.now(UTC).strftime("%Y%m%d%H%M%S"),
        validation_status=DatasetValidationStatus.PENDING,
        meta={
            "source": "user_csv_import",
            "label": label,
            "synthetic": False,
        },
    )
    session.add(dataset)
    session.flush()

    bars: list[OhlcvBar] = []
    seen: set[datetime] = set()
    dupes = 0
    for row in reader:
        ts = parse_timestamp(row["timestamp"])
        if ts in seen:
            dupes += 1
            continue
        seen.add(ts)
        vol = int(float(row.get("volume") or 0))
        bars.append(
            OhlcvBar(
                dataset_id=dataset.id,
                ts=ts,
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=vol,
            )
        )

    if not bars:
        raise ValueError("No bars parsed from CSV")

    session.add_all(bars)
    bars_sorted = sorted(bars, key=lambda x: x.ts)
    dataset.row_count = len(bars)
    dataset.coverage_start = bars_sorted[0].ts
    dataset.coverage_end = bars_sorted[-1].ts
    dataset.downloaded_at = datetime.now(UTC)
    dataset.validation_status = DatasetValidationStatus.VALIDATED
    dataset.meta["duplicate_rows_skipped"] = dupes
    session.flush()
    return dataset


def delete_dataset_bars(session: Session, dataset_id: uuid.UUID) -> None:
    session.execute(delete(OhlcvBar).where(OhlcvBar.dataset_id == dataset_id))
    ds = session.get(HistoricalDataset, dataset_id)
    if ds:
        ds.row_count = 0