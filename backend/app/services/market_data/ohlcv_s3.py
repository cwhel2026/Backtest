"""Optional S3-compatible mirror for OHLCV parquet (split Railway services / DR)."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.services.market_data.ohlcv_parquet import dataset_dir, store_root

logger = logging.getLogger(__name__)

_PREFIX = "ohlcv"


def _client():
    settings = get_settings()
    if not settings.ohlcv_s3_configured:
        return None
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 required for OHLCV S3 mirror — pip install boto3") from exc
    return boto3.client(
        "s3",
        endpoint_url=settings.ohlcv_s3_endpoint or None,
        aws_access_key_id=settings.ohlcv_s3_access_key,
        aws_secret_access_key=settings.ohlcv_s3_secret_key,
        region_name=settings.ohlcv_s3_region or "auto",
    )


def s3_key(dataset_id: UUID | str, filename: str) -> str:
    return f"{_PREFIX}/{dataset_id}/{filename}"


def storage_uri_s3(dataset_id: UUID | str) -> str:
    settings = get_settings()
    bucket = settings.ohlcv_s3_bucket
    return f"s3://{bucket}/{_PREFIX}/{dataset_id}/"


def storage_uri_local(dataset_id: UUID | str) -> str:
    return f"file://{store_root().resolve()}/{dataset_id}/"


def s3_list_parquet_keys(dataset_id: UUID | str) -> list[str]:
    client = _client()
    if not client:
        return []
    settings = get_settings()
    prefix = f"{_PREFIX}/{dataset_id}/"
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.ohlcv_s3_bucket, Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if key.endswith(".parquet"):
                keys.append(key)
    return keys


def s3_has_dataset(dataset_id: UUID | str) -> bool:
    return len(s3_list_parquet_keys(dataset_id)) > 0


def sync_dataset_to_s3(dataset_id: UUID | str) -> int:
    """Upload local parquet shards to S3. Returns files uploaded."""
    client = _client()
    if not client:
        return 0
    settings = get_settings()
    folder = store_root() / str(dataset_id)
    if not folder.is_dir():
        return 0
    uploaded = 0
    for path in folder.glob("*.parquet"):
        client.upload_file(str(path), settings.ohlcv_s3_bucket, s3_key(dataset_id, path.name))
        uploaded += 1
    return uploaded


def pull_dataset_from_s3(dataset_id: UUID | str) -> int:
    """Download S3 shards missing locally. Returns files pulled."""
    client = _client()
    if not client:
        return 0
    settings = get_settings()
    keys = s3_list_parquet_keys(dataset_id)
    if not keys:
        return 0
    folder = dataset_dir(dataset_id)
    pulled = 0
    for key in keys:
        name = Path(key).name
        dest = folder / name
        if dest.exists():
            continue
        client.download_file(settings.ohlcv_s3_bucket, key, str(dest))
        pulled += 1
    return pulled


def check_s3_reachable() -> tuple[bool, str]:
    settings = get_settings()
    if not settings.ohlcv_s3_configured:
        return True, "S3 mirror not configured"
    client = _client()
    if not client:
        return False, "boto3 unavailable"
    try:
        client.head_bucket(Bucket=settings.ohlcv_s3_bucket)
        return True, f"bucket {settings.ohlcv_s3_bucket} reachable"
    except Exception as exc:
        return False, str(exc)