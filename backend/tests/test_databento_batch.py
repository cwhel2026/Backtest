from unittest.mock import MagicMock, patch

import pandas as pd

from app.services.market_data.databento_batch import (
    _allowed_upload_name,
    complete_upload_session,
    init_upload_session,
    list_purchased_batch_jobs,
    save_upload_chunk,
    stream_dbn_file,
)
from app.services.market_data.dbn_symbology import SymbologyResolver


def test_symbol_roots():
    assert SymbologyResolver._root_from_label("MNQ.c.0") == "MNQ"
    assert SymbologyResolver._root_from_label("MES.c.0") == "MES"
    assert SymbologyResolver._root_from_label("GC.c.0") is None


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
@patch("app.services.market_data.databento_batch.write_bars")
def test_stream_dbn_file_chunked(mock_write, mock_store_cls, tmp_path):
    path = tmp_path / "t.dbn.zst"
    path.write_bytes(b"x")
    store = MagicMock()
    store.schema = "ohlcv-1m"
    store.dataset = "GLBX.MDP3"
    store.symbols = ["MNQ.c.0"]
    store.symbology = None
    store.to_df.return_value = iter(
        [
            pd.DataFrame(
                {
                    "open": [1.0],
                    "high": [1.1],
                    "low": [0.9],
                    "close": [1.05],
                    "volume": [10],
                    "symbol": ["MNQ.c.0"],
                },
                index=pd.date_range("2024-01-01", periods=1, freq="min", tz="UTC"),
            )
        ]
    )
    mock_store_cls.from_file.return_value = store
    from uuid import uuid4

    sinks = {
        "MNQ": {
            "dataset_id": uuid4(),
            "buffer": [],
            "rows_written": 0,
        }
    }
    meta = stream_dbn_file(path, sinks)
    assert meta["mapped_rows"] == 1
    assert mock_write.called or sinks["MNQ"]["buffer"]


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
    import ast
    import app.services.market_data.databento_batch as mod

    assert not hasattr(mod, "submit_databento_batch_job")
    tree = ast.parse(open(mod.__file__).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "submit_job":
                raise AssertionError("databento_batch must not call batch.submit_job")