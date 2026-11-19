"""Databento batch jobs: list/download existing purchases, decode DBN/zstd, import to parquet.

Never calls batch.submit_job — new paid requests require a separate explicit API.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from databento import DBNStore

from app.backtest.bars import Bar
from app.core.config import get_settings
from app.services.instruments import PRIMARY_RESEARCH_SYMBOLS
from app.services.market_data.databento_client import client as databento_client
from app.services.market_data.databento_ingest import DATABENTO_FUTURES_DATASET, DATABENTO_OHLCV_SCHEMA
from app.services.market_data.dbn_symbology import SymbologyResolver
from app.services.market_data.dataset_catalog import (
    create_pending_dataset,
    finalize_dataset_after_write,
    find_validated_duplicate,
    ingest_fingerprint,
)
from app.services.market_data.derived_timeframes import derive_timeframes_from_1m_parent
from app.services.market_data.ohlcv_parquet import bar_count, write_bars
from app.services.market_data.validate_dataset import validate_and_persist

ALLOWED_UPLOAD_SUFFIXES = (".dbn", ".dbn.zst", ".zst")
MAX_UPLOAD_BYTES = 2_000_000_000
MAX_CHUNK_BYTES = 12 * 1024 * 1024
MAX_EXPAND_RATIO = 50
DBN_DF_CHUNK = 25_000
BAR_WRITE_BATCH = 4_000
MIN_FREE_BYTES = 2_000_000_000  # require ~2GB free before import


def batch_staging_root() -> Path:
    from app.services.market_data.storage_backend import ensure_ohlcv_storage, resolved_store_path

    ensure_ohlcv_storage()
    path = resolved_store_path().parent / "databento_batch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def upload_staging_root() -> Path:
    base = batch_staging_root().parent / "databento_uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _disk_space_ok(path: Path) -> None:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        raise ValueError(f"Cannot check disk space: {exc}") from exc
    if usage.free < MIN_FREE_BYTES:
        raise ValueError(
            f"Insufficient disk space at {path}: {usage.free // (1024**2)} MB free "
            f"(need at least {MIN_FREE_BYTES // (1024**2)} MB for batch import)"
        )


def list_purchased_batch_jobs() -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.databento_configured:
        return []
    c = databento_client()
    jobs = c.batch.list_jobs(states="done,processing,queued,expired")
    return [
        {
            "id": j.get("id"),
            "state": j.get("state"),
            "dataset": j.get("dataset"),
            "schema": j.get("schema"),
            "symbols": j.get("symbols"),
            "start": j.get("start"),
            "end": j.get("end"),
            "size_bytes": j.get("size"),
            "encoding": j.get("encoding"),
            "compression": j.get("compression"),
        }
        for j in jobs
    ]


def download_batch_job_files(job_id: str, output_dir: Path) -> list[Path]:
    if not get_settings().databento_configured:
        raise ValueError("DATABENTO_API_KEY not configured")
    c = databento_client()
    files_meta = c.batch.list_files(job_id)
    if not files_meta:
        raise ValueError(f"Batch job {job_id} has no downloadable files (incomplete or expired?)")
    paths = c.batch.download(job_id, output_dir=str(output_dir))
    manifest = {"job_id": job_id, "files": files_meta, "downloaded": [str(p) for p in paths]}
    (output_dir / "batch_manifest.json").write_text(json.dumps(manifest, default=str), encoding="utf-8")
    return [Path(p) for p in paths]


def _iter_dbn_frames(store: DBNStore):
    schema = str(store.schema or DATABENTO_OHLCV_SCHEMA)
    df_or_it = store.to_df(schema=schema, count=DBN_DF_CHUNK)
    if hasattr(df_or_it, "__iter__") and not hasattr(df_or_it, "columns"):
        for frame in df_or_it:
            if frame is not None and not frame.empty:
                yield frame
    elif df_or_it is not None and not getattr(df_or_it, "empty", True):
        yield df_or_it


def _bar_from_row(ts, row) -> Bar:
    bar_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    if getattr(bar_ts, "tzinfo", None) is None:
        bar_ts = bar_ts.replace(tzinfo=UTC)
    else:
        bar_ts = bar_ts.astimezone(UTC)
    return Bar(
        ts=bar_ts,
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=int(row.get("volume", 0)),
    )


def stream_dbn_file(
    path: Path,
    sinks: dict[str, dict],
) -> dict:
    """Stream one DBN file into per-root buffers (memory bounded by BAR_WRITE_BATCH flushes)."""
    if path.stat().st_size == 0:
        raise ValueError(f"Empty file: {path.name}")
    store = DBNStore.from_file(path)
    schema = str(store.schema or DATABENTO_OHLCV_SCHEMA)
    if "ohlcv" not in schema.lower():
        raise ValueError(f"{path.name}: schema {schema} is not OHLCV")

    resolver = SymbologyResolver.from_store(store)
    symbol_col = None
    instrument_col = None
    meta = {
        "file": path.name,
        "dataset": str(store.dataset),
        "schema": schema,
        "file_symbols": resolver.file_symbols,
        "resolver": resolver.diagnostics,
    }
    unmapped = 0
    mapped = 0

    for frame in _iter_dbn_frames(store):
        if symbol_col is None:
            symbol_col = next((c for c in ("symbol", "raw_symbol") if c in frame.columns), None)
            instrument_col = next((c for c in ("instrument_id",) if c in frame.columns), None)
        for ts, row in frame.iterrows():
            root = resolver.resolve_row(row, symbol_col, instrument_col)
            if not root or root not in sinks:
                unmapped += 1
                continue
            mapped += 1
            bar = _bar_from_row(ts, row)
            buf: list = sinks[root]["buffer"]
            buf.append((bar.ts, bar.open, bar.high, bar.low, bar.close, bar.volume))
            if len(buf) >= BAR_WRITE_BATCH:
                write_bars(sinks[root]["dataset_id"], buf)
                sinks[root]["buffer"] = []
                sinks[root]["rows_written"] += len(buf)

    resolver.assert_ready()
    meta["mapped_rows"] = mapped
    meta["unmapped_rows"] = unmapped
    meta["unmapped_samples"] = resolver.unmapped_samples
    if mapped == 0:
        raise ValueError(f"{path.name}: no rows mapped to MNQ/MES/MGC — symbology mismatch")
    if unmapped > 0 and unmapped / max(1, mapped + unmapped) > 0.05:
        raise ValueError(
            f"{path.name}: too many unmapped rows ({unmapped}/{mapped + unmapped}). "
            f"Samples: {resolver.unmapped_samples[:5]}"
        )
    return meta


def collect_dbn_paths(directory: Path) -> list[Path]:
    paths: list[Path] = []
    for p in sorted(directory.rglob("*")):
        if not p.is_file() or p.name == "batch_manifest.json":
            continue
        lower = p.name.lower()
        if lower.endswith(".dbn.zst") or lower.endswith(".dbn") or lower.endswith(".zst"):
            paths.append(p)
    return paths


def import_dbn_directory(
    session,
    directory: Path,
    *,
    source: str,
    job_id: str | None = None,
    fingerprint_override: str | None = None,
    on_progress: Callable[[str, int], None] | None = None,
) -> list:
    from sqlalchemy import select

    from app.models.instrument import Instrument

    _disk_space_ok(directory)
    paths = collect_dbn_paths(directory)
    if not paths:
        raise ValueError("No .dbn or .dbn.zst files found")

    file_metas: list[dict] = []
    sinks: dict[str, dict] = {}
    range_start: dict[str, datetime] = {}
    range_end: dict[str, datetime] = {}

    # First pass: discover which roots appear (stream with small peeks) — create datasets
    roots_seen: set[str] = set()
    for path in paths:
        store = DBNStore.from_file(path)
        res = SymbologyResolver.from_store(store)
        for sym in res.file_symbols:
            root = SymbologyResolver._root_from_label(sym)
            if root:
                roots_seen.add(root)
        roots_seen.update(res.id_to_root.values())
        roots_seen.update(res.raw_to_root.values())

    if not roots_seen:
        raise ValueError("Cannot determine MNQ/MES/MGC from batch file headers — missing symbology")

    for root in sorted(roots_seen & set(PRIMARY_RESEARCH_SYMBOLS)):
        inst = session.execute(select(Instrument).where(Instrument.symbol == root)).scalar_one_or_none()
        if not inst:
            continue
        # provisional range; refined after import
        start = datetime(2021, 11, 19, tzinfo=UTC)
        end = datetime(2026, 11, 18, tzinfo=UTC)
        fp = fingerprint_override or ingest_fingerprint(
            provider_slug="databento",
            instrument_symbol=root,
            timeframe="1m",
            start=start,
            end=end,
        )
        dup = find_validated_duplicate(session, fingerprint=fp, instrument_id=inst.id, timeframe="1m")
        if dup and source == "databento_batch_api":
            if on_progress:
                on_progress(f"{root}: already imported (duplicate skipped)", 90)
            continue

        dataset = create_pending_dataset(
            session,
            provider_slug="databento",
            instrument_id=inst.id,
            timeframe="1m",
            fingerprint=fp,
            meta={
                "source": "databento_batch",
                "provider": "databento",
                "import_source": source,
                "databento_batch_job_id": job_id,
                "databento_dataset": DATABENTO_FUTURES_DATASET,
                "schema": DATABENTO_OHLCV_SCHEMA,
                "price_stitching": False,
                "series_kind": "batch_as_purchased",
                "execution_accurate": False,
                "continuous_research_only": True,
                "symbology_note": "Continuous research series; rollovers not stitched.",
            },
        )
        session.flush()
        sinks[root] = {
            "dataset_id": dataset.id,
            "dataset": dataset,
            "instrument": inst,
            "buffer": [],
            "rows_written": 0,
            "fingerprint": fp,
        }

    if not sinks:
        raise ValueError("No datasets created — duplicates or unknown symbols")

    for i, path in enumerate(paths):
        if on_progress:
            on_progress(f"Processing {path.name}", 15 + int(55 * i / max(1, len(paths))))
        meta = stream_dbn_file(path, sinks)
        file_metas.append(meta)

    created = []
    for root, sink in sinks.items():
        if sink["buffer"]:
            write_bars(sink["dataset_id"], sink["buffer"])
            sink["rows_written"] += len(sink["buffer"])
            sink["buffer"] = []
        if bar_count(sink["dataset_id"]) == 0:
            raise ValueError(f"{root}: no bars written after processing")
        dataset = sink["dataset"]
        finalize_dataset_after_write(session, dataset)
        m = dict(dataset.meta or {})
        m["dbn_files"] = file_metas
        dataset.meta = m
        if on_progress:
            on_progress(f"Checking data quality for {root}", 75)
        result = validate_and_persist(
            session,
            dataset,
            symbol=root,
            tick_size=sink["instrument"].tick_size,
            instrument_trading_hours=sink["instrument"].trading_hours or {},
            sample_large=True,
        )
        qclass = result.get("quality_class", "unknown")
        if qclass == "blocked":
            raise ValueError(f"{root}: validation BLOCKED — {result.get('notes')}")
        coverage_start = dataset.coverage_start or datetime(2021, 11, 19, tzinfo=UTC)
        coverage_end = dataset.coverage_end or datetime(2026, 11, 18, tzinfo=UTC)
        derive_timeframes_from_1m_parent(
            session,
            parent=dataset,
            symbol=root,
            instrument_id=sink["instrument"].id,
            range_start=coverage_start,
            range_end=coverage_end,
            tick_size=sink["instrument"].tick_size,
            trading_hours=sink["instrument"].trading_hours or {},
            parent_fingerprint=sink["fingerprint"],
            on_progress=on_progress,
        )
        created.append(dataset)

    if not created:
        raise ValueError("Import produced no validated datasets")
    if on_progress:
        on_progress("Ready for backtesting", 98)
    return created


def run_batch_job_import(session, payload: dict) -> dict:
    job_id = payload.get("databento_batch_job_id")
    if not job_id:
        raise ValueError("databento_batch_job_id required")

    def progress(msg: str, pct: int) -> None:
        rid = payload.get("research_job_id")
        if not rid:
            return
        from app.models.research import ResearchJob

        job = session.get(ResearchJob, uuid.UUID(rid))
        if job:
            job.message = msg
            job.progress_pct = min(99, pct)
            session.flush()

    progress("Downloading historical data", 5)
    staging = batch_staging_root() / str(job_id)
    staging.mkdir(parents=True, exist_ok=True)
    _disk_space_ok(staging)
    try:
        download_batch_job_files(job_id, staging)
    except Exception as exc:
        raise ValueError(f"Batch download failed: {exc}") from exc
    progress("Download complete — processing candles", 20)
    try:
        datasets = import_dbn_directory(
            session,
            staging,
            source="databento_batch_api",
            job_id=job_id,
            on_progress=progress,
        )
    except Exception:
        (staging / "IMPORT_FAILED").write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
        raise
    (staging / "IMPORT_COMPLETE").write_text(json.dumps({"datasets": [str(d.id) for d in datasets]}), encoding="utf-8")
    from app.services.market_data.storage_backend import after_local_write

    for d in datasets:
        try:
            after_local_write(d.id)
        except Exception:
            pass
    return {
        "datasets": [str(d.id) for d in datasets],
        "instrument_symbols": [d.meta.get("instrument_symbol") for d in datasets],
    }


def run_upload_import(session, payload: dict) -> dict:
    upload_id = payload.get("upload_id")
    if not upload_id:
        raise ValueError("upload_id required")
    directory = upload_staging_root() / upload_id / "files"
    if not directory.is_dir():
        raise ValueError("Upload session not found")

    def progress(msg: str, pct: int) -> None:
        rid = payload.get("research_job_id")
        if not rid:
            return
        from app.models.research import ResearchJob

        job = session.get(ResearchJob, uuid.UUID(rid))
        if job:
            job.message = msg
            job.progress_pct = min(99, pct)
            session.flush()

    progress("Processing uploaded files", 10)
    _disk_space_ok(directory)
    datasets = import_dbn_directory(session, directory, source="iphone_upload", on_progress=progress)
    shutil.rmtree(upload_staging_root() / upload_id, ignore_errors=True)
    return {"datasets": [str(d.id) for d in datasets]}


def _allowed_upload_name(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(s) for s in ALLOWED_UPLOAD_SUFFIXES)


def init_upload_session(file_specs: list[dict]) -> dict:
    upload_id = hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:16]
    root = upload_staging_root() / upload_id
    (root / "files").mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    for spec in file_specs:
        name = Path(spec["name"]).name
        if not _allowed_upload_name(name):
            raise ValueError(f"Unsupported file type: {name}")
        size = int(spec["size"])
        if size <= 0 or size > MAX_UPLOAD_BYTES:
            raise ValueError(f"Invalid size for {name}")
        files[name] = {"size": size, "chunks": []}
    manifest = {"upload_id": upload_id, "files": files, "created_at": datetime.now(UTC).isoformat()}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def save_upload_chunk(upload_id: str, file_name: str, index: int, total: int, data: bytes) -> dict:
    name = Path(file_name).name
    if not _allowed_upload_name(name):
        raise ValueError("Invalid file type")
    if len(data) > MAX_CHUNK_BYTES:
        raise ValueError("Chunk too large")
    root = upload_staging_root() / upload_id
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("Unknown upload session")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    finfo = manifest["files"].get(name)
    if not finfo:
        raise ValueError("File not in upload session")
    part = root / "files" / f"{name}.part{index:05d}"
    part.write_bytes(data)
    chunks = set(finfo.get("chunks", []))
    chunks.add(index)
    finfo["chunks"] = sorted(chunks)
    finfo["total_chunks"] = total
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return {"received": index, "chunks_done": len(chunks), "total_chunks": total}


def complete_upload_session(upload_id: str) -> list[str]:
    root = upload_staging_root() / upload_id
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assembled: list[str] = []
    for name, finfo in manifest["files"].items():
        total = int(finfo.get("total_chunks") or 0)
        chunks = set(finfo.get("chunks") or [])
        if total and len(chunks) != total:
            raise ValueError(f"Incomplete upload for {name}: {len(chunks)}/{total} chunks")
        dest = root / "files" / name
        with open(dest, "wb") as out:
            for idx in sorted(chunks):
                part = root / "files" / f"{name}.part{idx:05d}"
                if not part.exists():
                    raise ValueError(f"Missing chunk {idx} for {name}")
                out.write(part.read_bytes())
                part.unlink(missing_ok=True)
        if dest.stat().st_size > int(finfo["size"]) * MAX_EXPAND_RATIO:
            dest.unlink(missing_ok=True)
            raise ValueError(f"File {name} failed integrity check")
        assembled.append(name)
    manifest["completed_at"] = datetime.now(UTC).isoformat()
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return assembled