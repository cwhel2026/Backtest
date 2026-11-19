from datetime import UTC, datetime, timedelta

import pytest
from decimal import Decimal
from uuid import uuid4

from app.services.market_data.ohlcv_parquet import (
    bar_count,
    drop_dataset,
    has_store,
    read_bars,
    set_store_dir,
    trim_dataset,
    write_bars,
)


@pytest.fixture(autouse=True)
def _reset_store_dir():
    yield
    set_store_dir(None)


def _bar(ts: datetime, px: str = "5200"):
    d = Decimal(px)
    return (ts, d, d + 1, d - 1, d, 10)


def test_write_read_and_day_rollover(tmp_path):
    set_store_dir(tmp_path)
    ds = uuid4()
    day1 = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
    day2 = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
    write_bars(ds, [_bar(day1, "1"), _bar(day2, "2")])
    assert has_store(ds)
    assert bar_count(ds) == 2
    assert (tmp_path / str(ds) / "2026-11-10.parquet").exists()
    assert (tmp_path / str(ds) / "2026-11-11.parquet").exists()
    rows = read_bars(ds)
    assert [r[0] for r in rows] == [day1, day2]
    assert rows[1][4] == Decimal("2.0") or rows[1][4] == Decimal("2")


def test_merge_is_idempotent(tmp_path):
    set_store_dir(tmp_path)
    ds = uuid4()
    ts = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
    write_bars(ds, [_bar(ts, "10")])
    write_bars(ds, [_bar(ts, "11"), _bar(ts + timedelta(minutes=1), "12")])
    rows = read_bars(ds)
    assert len(rows) == 2
    assert rows[0][4] == Decimal("11.0") or rows[0][4] == Decimal("11")


def test_trim_drops_old_day_files(tmp_path):
    set_store_dir(tmp_path)
    ds = uuid4()
    old = datetime(2026, 10, 1, 12, tzinfo=UTC)
    keep = datetime(2026, 11, 18, 12, tzinfo=UTC)
    write_bars(ds, [_bar(old, "1"), _bar(keep, "2")])
    dropped = trim_dataset(ds, datetime(2026, 11, 1, tzinfo=UTC))
    assert dropped == 1
    rows = read_bars(ds)
    assert len(rows) == 1
    assert rows[0][0] == keep
    drop_dataset(ds)
    assert not has_store(ds)


def test_read_range_filters(tmp_path):
    set_store_dir(tmp_path)
    ds = uuid4()
    bars = [_bar(datetime(2026, 11, 10, i, tzinfo=UTC), str(i)) for i in range(10, 14)]
    write_bars(ds, bars)
    mid = datetime(2026, 11, 10, 11, tzinfo=UTC)
    end = datetime(2026, 11, 10, 12, tzinfo=UTC)
    got = read_bars(ds, start=mid, end=end)
    assert [r[0].hour for r in got] == [11, 12]
