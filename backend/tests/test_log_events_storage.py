"""Regression: stdlib logging must not receive structlog kwargs."""

import logging
from unittest import mock

import pytest

from app.services.market_data.storage_backend import ensure_ohlcv_storage
from app.util.log_events import log_event


def test_log_event_stdlib_safe(caplog):
    log = logging.getLogger("test_log_events")
    with caplog.at_level(logging.ERROR):
        log_event(log, logging.ERROR, "evt", detail="x", store="/data/ohlcv")
    assert any("evt" in r.message for r in caplog.records)


def test_ensure_ohlcv_storage_ephemeral_warning(caplog, tmp_path, monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.delenv("OHLCV_STORE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = mock.MagicMock()
    settings.on_railway = True
    settings.ohlcv_persistent_required = True
    settings.ohlcv_s3_configured = False
    settings.ohlcv_store_dir = "data/ohlcv"
    with (
        mock.patch("app.services.market_data.storage_backend.get_settings", return_value=settings),
        mock.patch("app.services.market_data.storage_health.get_settings", return_value=settings),
        mock.patch("app.services.market_data.storage_health.check_not_ephemeral", return_value=(False, "ephemeral")),
        mock.patch("app.services.market_data.storage_health.check_store_writable", return_value=(True, "ok")),
        caplog.at_level(logging.ERROR),
    ):
        out = ensure_ohlcv_storage()
    assert out["store_synchronized"] is True
    assert any("ohlcv_ephemeral" in r.message for r in caplog.records)