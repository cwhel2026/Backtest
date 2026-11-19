"""Resolve OHLCV storage layout for Railway volumes and optional S3 mirror."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.services.market_data import ohlcv_s3
from app.services.market_data.ohlcv_parquet import store_root

logger = logging.getLogger(__name__)

RAILWAY_VOLUME_MOUNT = Path("/data")
RAILWAY_DEFAULT_STORE = RAILWAY_VOLUME_MOUNT / "ohlcv"


def resolved_store_path() -> Path:
    settings = get_settings()
    raw = (settings.ohlcv_store_dir or "data/ohlcv").strip()
    path = Path(raw)
    if not path.is_absolute():
        if settings.on_railway and RAILWAY_VOLUME_MOUNT.is_dir():
            return RAILWAY_DEFAULT_STORE
        path = Path.cwd() / path
    return path


def ensure_ohlcv_storage() -> dict:
    """Create store directories; log warnings on ephemeral Railway layout."""
    settings = get_settings()
    root = store_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / ".railway").mkdir(exist_ok=True)

    from app.services.market_data.storage_health import check_not_ephemeral, check_store_writable

    writable, w_msg = check_store_writable()
    persist_ok, p_msg = check_not_ephemeral()
    s3_ok, s3_msg = (True, "n/a")
    if settings.ohlcv_s3_configured:
        s3_ok, s3_msg = ohlcv_s3.check_s3_reachable()

    deploy = "railway" if settings.on_railway else "local"
    split_worker = os.getenv("PROP_EDGE_ROLE", "api") == "worker"

    out = {
        "deploy": deploy,
        "role": os.getenv("PROP_EDGE_ROLE", "api"),
        "store_path": str(root.resolve()),
        "volume_mounted": RAILWAY_VOLUME_MOUNT.is_dir(),
        "writable": writable,
        "writable_detail": w_msg,
        "persistent_ok": persist_ok,
        "persistent_detail": p_msg,
        "s3_ok": s3_ok,
        "s3_detail": s3_msg,
        "split_worker_note": (
            "Worker and API need the same volume mount, or enable OHLCV_S3_* mirror for both services."
            if split_worker or deploy == "railway"
            else None
        ),
    }
    if settings.on_railway and settings.ohlcv_persistent_required and not persist_ok and not settings.ohlcv_s3_configured:
        logger.error("ohlcv_ephemeral_railway", detail=p_msg, store=str(root))
    elif not persist_ok:
        logger.warning("ohlcv_storage_ephemeral", detail=p_msg)
    return out


def canonical_storage_uri(dataset_id: UUID | str) -> str:
    settings = get_settings()
    local = ohlcv_s3.storage_uri_local(dataset_id)
    if settings.ohlcv_s3_configured:
        return f"{local};{ohlcv_s3.storage_uri_s3(dataset_id)}"
    return local


def hydrate_dataset_from_remote(dataset_id: UUID | str) -> bool:
    """If local parquet missing, pull from S3 mirror."""
    settings = get_settings()
    folder = store_root() / str(dataset_id)
    if folder.is_dir() and any(folder.glob("*.parquet")):
        return True
    if not settings.ohlcv_s3_configured:
        return False
    pulled = ohlcv_s3.pull_dataset_from_s3(dataset_id)
    return pulled > 0 or ohlcv_s3.s3_has_dataset(dataset_id)


def after_local_write(dataset_id: UUID | str) -> None:
    settings = get_settings()
    if settings.ohlcv_s3_configured:
        try:
            n = ohlcv_s3.sync_dataset_to_s3(dataset_id)
            if n:
                logger.info("ohlcv_s3_synced", dataset_id=str(dataset_id), files=n)
        except Exception as exc:
            logger.warning("ohlcv_s3_sync_failed", dataset_id=str(dataset_id), error=str(exc))