from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from app.services.market_data.databento_batch import (
    _allowed_upload_name,
    _root_from_symbol_label,
    bars_by_root_from_dbn,
    complete_upload_session,
    init_upload_session,
    list_purchased_batch_jobs,
    save_upload_chunk,
)


def test_symbol_roots():
    assert _root_from_symbol_label("MNQ.c.0") == "MNQ"
    assert _root_from_symbol_label("MES.c.0") == "MES"
    assert _root_from_symbol_label("GC.c.0") is None


def test_upload_suffix_validation():
    assert _allowed_upload_name("batch.dbn.zst")
    assert not _allowed_upload_name("evil.exe")


@patch("app.services.market_data.databento_batch.databento_client")
def test_list_jobs_no_submit(mock_client):
    mock_client.return_value.batch.list_jobs.return_value = [{"id": "JOB-1", "state": "done"}]
    with patch("app.services.market_data.databento_batch.get_settings") as gs:
        gs.return_value.databento_configured = True
        gs.return_value.databento_api_key = "k"
        jobs = list_purchased_batch_jobs()
    assert jobs[0]["id"] == "JOB-1"
    mock_client.return_value.batch.submit_job.assert_not_called()


@patch("app.services.market_data.databento_batch.DBNStore")
def test_bars_by_root_from_dbn(mock_store_cls, tmp_path):
    path = tmp_path / "t.dbn.zst"
    path.write_bytes(b"x")
    store = MagicMock()
    store.schema = "ohlcv-1m"
    store.dataset = "GLBX.MDP3"
    store.symbols = ["MNQ.c.0"]
    store.stype_in = "continuous"
    store.compression = "zstd"
    idx = pd.date_range("2024-01-01", periods=2, freq="min", tz=UTC)
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.1],
            "high": [1.1, 1.2],
            "low": [0.9, 1.0],
            "close": [1.05, 1.15],
            "volume": [10, 12],
            "symbol": ["MNQ.c.0", "MNQ.c.0"],
        },
        index=idx,
    )
    store.to_df.return_value = frame
    mock_store_cls.from_file.return_value = store
    by_root, meta = bars_by_root_from_dbn(path)
    assert "MNQ" in by_root
    assert len(by_root["MNQ"]) == 2


def test_upload_chunk_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.market_data.databento_batch.upload_staging_root",
        lambda: tmp_path,
    )
    manifest = init_upload_session([{"name": "x.dbn.zst", "size": 10}])
    uid = manifest["upload_id"]
    save_upload_chunk(uid, "x.dbn.zst", 0, 1, b"1234567890")
    names = complete_upload_session(uid)
    assert names == ["x.dbn.zst"]
    assert (tmp_path / uid / "files" / "x.dbn.zst").read_bytes() == b"1234567890"


def test_prevent_paid_request_no_submit_endpoint():
    """Bundle import must not expose submit_job in our service module."""
    import app.services.market_data.databento_batch as mod

    assert not hasattr(mod, "submit_databento_batch_job")