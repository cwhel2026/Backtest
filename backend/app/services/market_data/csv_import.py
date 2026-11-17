"""Import user-provided OHLCV CSV into a historical dataset."""

import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.backtest import OhlcvBar
from app.models.market_data import HistoricalDataset
from app.services.market_data.bar_storage import persist_bars_to_dataset


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
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"timestamp", "open", "high", "low", "close"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("CSV must include columns: timestamp, open, high, low, close (volume optional)")

    rows: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]] = []
    for row in reader:
        ts = parse_timestamp(row["timestamp"])
        vol = int(float(row.get("volume") or 0))
        rows.append(
            (
                ts,
                Decimal(row["open"]),
                Decimal(row["high"]),
                Decimal(row["low"]),
                Decimal(row["close"]),
                vol,
            )
        )

    return persist_bars_to_dataset(
        session,
        provider_slug=provider_slug,
        instrument_id=instrument_id,
        timeframe=timeframe,
        bars=rows,
        meta={"source": "user_csv_import", "label": label},
    )


def delete_dataset_bars(session: Session, dataset_id: uuid.UUID) -> None:
    session.execute(delete(OhlcvBar).where(OhlcvBar.dataset_id == dataset_id))
    ds = session.get(HistoricalDataset, dataset_id)
    if ds:
        ds.row_count = 0