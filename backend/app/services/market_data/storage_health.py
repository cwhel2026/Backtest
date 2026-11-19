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
    return {
        "configured_dir": settings.ohlcv_store_dir,
        "resolved_path": str(root.resolve()),
        "persistent_volume_hint": settings.ohlcv_persistent_required,
        "s3_bucket": settings.ohlcv_s3_bucket or None,
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
    if settings.ohlcv_s3_bucket:
        return True, f"S3 backend configured ({settings.ohlcv_s3_bucket})"
    if not settings.ohlcv_persistent_required:
        return True, "persistent check disabled (dev)"
    cwd_data = (Path.cwd() / "data" / "ohlcv").resolve()
    if str(root) == str(cwd_data) and os.getenv("RAILWAY_ENVIRONMENT"):
        return (
            False,
            "OHLCV_STORE_DIR appears ephemeral (repo-local data/ohlcv on Railway). Mount a volume at /data/ohlcv.",
        )
    if str(root).startswith("/data") or "volume" in str(root).lower():
        return True, f"path looks volume-backed: {root}"
    if root.is_absolute() and root.exists():
        return True, f"using absolute store path {root}"
    return False, f"set OHLCV_STORE_DIR to a mounted volume (currently {root})"


def check_database(session: Session) -> tuple[bool, str]:
    try:
        session.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as exc:
        return False, str(exc)