from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from app.backtest.bars import Bar
from app.services.market_data.dbn_symbology import SymbologyResolver
from app.services.market_data.streaming_aggregate import StreamingAggregator, floor_bucket_ts


def test_symbology_continuous_symbols():
    r = SymbologyResolver()
    r.file_symbols = ["MNQ.c.0", "MES.c.0"]
    r.raw_to_root["MNQ.C.0"] = "MNQ"
    assert SymbologyResolver._root_from_label("MNQ.c.0") == "MNQ"
    assert SymbologyResolver._root_from_label("CL.c.0") is None


def test_symbology_instrument_id_mapping():
    r = SymbologyResolver()
    r.id_to_root["12345"] = "MES"
    row = pd.Series({"instrument_id": "12345", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1})
    assert r.resolve_row(row, "symbol", "instrument_id") == "MES"


def test_symbology_refuses_unknown_without_metadata():
    r = SymbologyResolver()
    with __import__("pytest").raises(ValueError):
        r.assert_ready()


def test_streaming_aggregator_carries_boundary():
    agg = StreamingAggregator("5m")
    t0 = datetime(2024, 1, 1, 14, 0, tzinfo=UTC)
    bars = [
        Bar(ts=t0, open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=1),
        Bar(ts=t0.replace(minute=1), open=Decimal(2), high=Decimal(2), low=Decimal(2), close=Decimal(2), volume=1),
        Bar(ts=t0.replace(minute=5), open=Decimal(3), high=Decimal(3), low=Decimal(3), close=Decimal(3), volume=1),
    ]
    completed = []
    for b in bars:
        completed.extend(agg.ingest_1m(b))
    completed.extend(agg.flush())
    assert len(completed) == 2
    assert completed[0].ts == floor_bucket_ts(t0, 5)
    assert completed[0].open == Decimal(1)
    assert completed[0].close == Decimal(2)


def test_streaming_aggregator_across_files():
    """Simulate two sequential 1m streams (file boundary) in same 5m bucket."""
    agg = StreamingAggregator("5m")
    t0 = datetime(2024, 1, 1, 14, 3, tzinfo=UTC)
    part_a = [
        Bar(ts=t0, open=Decimal(1), high=Decimal(2), low=Decimal(1), close=Decimal("1.5"), volume=10),
    ]
    part_b = [
        Bar(ts=t0.replace(minute=4), open=Decimal("1.5"), high=Decimal(3), low=Decimal(1), close=Decimal(2), volume=5),
    ]
    for b in part_a + part_b:
        agg.ingest_1m(b)
    done = agg.flush()
    assert len(done) == 1
    assert done[0].volume == 15
    assert done[0].high == Decimal(3)


def test_memory_bounded_derive_writes(tmp_path, monkeypatch):
    """Stress: many days of 1m parquet; streaming derive should not require full RAM."""
    import resource
    from datetime import timedelta
    from uuid import uuid4

    from app.services.market_data.derived_timeframes import _bars_from_day_parquet
    from app.services.market_data.ohlcv_parquet import set_store_dir, write_bars
    from app.services.market_data.streaming_aggregate import StreamingAggregator

    set_store_dir(tmp_path)
    ds_id = uuid4()
    base = tmp_path / str(ds_id)
    base.mkdir(parents=True)
    t0 = datetime(2024, 1, 1, 14, 0, tzinfo=UTC)
    for day in range(14):
        rows = []
        for minute in range(0, 60 * 6, 1):
            t = t0 + timedelta(days=day, minutes=minute)
            rows.append((t, Decimal(1), Decimal(1), Decimal(1), Decimal(1), 1))
        write_bars(ds_id, rows)

    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    agg = StreamingAggregator("5m")
    out_count = 0
    for path in sorted(base.glob("*.parquet")):
        for bar in _bars_from_day_parquet(path):
            out_count += len(agg.ingest_1m(bar))
    out_count += len(agg.flush())
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KB; macOS reports bytes — cap at 512MB either way
    delta_kb = max(0, rss_after - rss_before)
    assert out_count > 0
    assert delta_kb < 512_000, f"RSS growth too high: {delta_kb} KB"