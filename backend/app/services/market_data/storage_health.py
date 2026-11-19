"""Parquet store persistence checks for Railway / volume mounts."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.market_data.ohlcv_parquet import bar_count, set_store_dir, store_root, write_bars


def store_paths() -> dict:
    settings = get_settings()
    root = store_root()
    volume = Path("/data")
    return {
        "configured_dir": settings.ohlcv_store_dir,
        "resolved_path": str(root.resolve()),
        "persistent_volume_hint": settings.ohlcv_persistent_required,
        "s3_bucket": settings.ohlcv_s3_bucket or None,
        "s3_mirror_configured": settings.ohlcv_s3_configured,
        "railway_volume_mounted": volume.is_dir(),
        "recommended_path": "/data/ohlcv",
        "on_railway": settings.on_railway,
    }


def check_store_writable() -> tuple[bool, str]:
    try:
        root = store_root()
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write_probe"
        probe.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
        probe.unlink(missing_ok=True)
        test_id = uuid.uuid4()
        ts = datetime.now(UTC)
        write_bars(
            test_id,
            [(ts, Decimal(1), Decimal(1), Decimal(1), Decimal(1), 0)],
        )
        n = bar_count(test_id)
        # cleanup probe dataset folder
        import shutil

        shutil.rmtree(store_root() / str(test_id), ignore_errors=True)
        return True, f"writable; probe wrote {n} bar"
    except Exception as exc:
        return False, str(exc)


def check_not_ephemeral() -> tuple[bool, str]:
    settings = get_settings()
    root = store_root().resolve()
    if settings.ohlcv_s3_configured:
        return True, f"S3 mirror configured ({settings.ohlcv_s3_bucket}) — local cache at {root}"
    if not settings.ohlcv_persistent_required:
        return True, "persistent check disabled (dev)"
    cwd_data = (Path.cwd() / "data" / "ohlcv").resolve()
    if settings.on_railway and str(root) == str(cwd_data):
        return (
            False,
            "Ephemeral container path detected. Mount a Railway volume at /data and set OHLCV_STORE_DIR=/data/ohlcv.",
        )
    if settings.on_railway and not Path("/data").is_dir():
        return (
            False,
            "Railway volume /data not mounted. Attach a volume to this service (mount path /data).",
        )
    if str(root).startswith("/data/ohlcv") or str(root) == "/data/ohlcv":
        return True, f"Railway volume store: {root}"
    if str(root).startswith("/data") or "volume" in str(root).lower():
        return True, f"path looks volume-backed: {root}"
    if settings.on_railway:
        return False, f"On Railway, use OHLCV_STORE_DIR=/data/ohlcv (currently {root})"
    return True, f"local dev store: {root}"


def check_database(session: Session) -> tuple[bool, str]:
    try:
        session.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as exc:
        return False, str(exc)