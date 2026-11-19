"""Railway storage path resolution (no Railway runtime required)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.market_data.storage_backend import resolved_store_path
from app.services.market_data.storage_health import check_not_ephemeral


def test_resolved_store_honours_absolute_config():
    with patch("app.services.market_data.storage_backend.get_settings") as gs:
        gs.return_value.ohlcv_store_dir = "/data/ohlcv"
        gs.return_value.on_railway = True
        assert resolved_store_path() == Path("/data/ohlcv")


def test_railway_ephemeral_repo_path_rejected():
    mock_settings = MagicMock()
    mock_settings.ohlcv_s3_configured = False
    mock_settings.ohlcv_persistent_required = True
    mock_settings.on_railway = True
    ephemeral = Path("/app/backend/data/ohlcv")
    with (
        patch("app.services.market_data.storage_health.get_settings", return_value=mock_settings),
        patch("app.services.market_data.storage_health.store_root", return_value=ephemeral),
        patch("app.services.market_data.storage_health.Path") as P,
    ):
        data_path = MagicMock()
        data_path.is_dir.return_value = False
        P.side_effect = lambda arg=None, *a, **k: data_path if arg == "/data" else Path(arg or ".")
        ok, msg = check_not_ephemeral()
    assert not ok
    assert "volume" in msg.lower() or "ephemeral" in msg.lower()