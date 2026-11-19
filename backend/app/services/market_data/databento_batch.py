"""Databento batch jobs: list/download existing purchases, decode DBN/zstd, import to parquet.

Never calls batch.submit_job — new paid requests require a separate explicit API.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from collections import defaultdict
from dataclasses import dataclass
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
from app.services.market_data.dataset_catalog import (
    create_pending_dataset,
    finalize_dataset_after_write,
    ingest_fingerprint,
)
from app.services.market_data.derived_timeframes import derive_timeframes_from_1m_parent
from app.services.market_data.ohlcv_parquet import write_bars
from app.services.market_data.validate_dataset import validate_and_persist

PRIMARY_ROOT_PATTERN = re.compile(r"^(MNQ|MES|MGC)", re.I)
ALLOWED_UPLOAD_SUFFIXES = (".dbn", ".dbn.zst", ".zst")
MAX_UPLOAD_BYTES = 2_000_000_000
MAX_CHUNK_BYTES = 12 * 1024 * 1024
MAX_EXPAND_RATIO = 50


def batch_staging_root() -> Path:
    from app.services.market_data.storage_backend import ensure_ohlcv_storage

    ensure_ohlcv_storage()
    from app.services.market_data.storage_backend import resolved_store_path

    base = resolved_store_path().parent
    path = base / "databento_batch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def upload_staging_root() -> Path:
    base = batch_staging_root().parent / "databento_uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def list_purchased_batch_jobs() -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.databento_configured:
        return []
    c = databento_client()
    jobs = c.batch.list_jobs(states="done,processing,queued")
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
    c.batch.list_files(job_id)
    paths = c.batch.download(job_id, output_dir=str(output_dir))
    return [Path(p) for p in paths]


def _root_from_symbol_label(label: str) -> str | None:
    if not label:
        return None
    up = str(label).strip().upper()
    for root in PRIMARY_RESEARCH_SYMBOLS:
        if up == root or up.startswith(f"{root}.") or up.startswith(root) and not up[len(root) :1].isalpha():
            return root
    m = PRIMARY_ROOT_PATTERN.match(up)
    return m.group(1).upper() if m else None


def _dataframe_from_store(store: DBNStore):
    schema = str(store.schema or DATABENTO_OHLCV_SCHEMA)
    df = store.to_df(schema=schema)
    if hasattr(df, "__iter__") and not hasattr(df, "columns"):
        import pandas as pd

        frames = list(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return df


def bars_by_root_from_dbn(path: Path) -> tuple[dict[str, list[Bar]], dict]:
    if path.stat().st_size == 0:
        raise ValueError(f"Empty file: {path.name}")
    store = DBNStore.from_file(path)
    schema = str(store.schema or DATABENTO_OHLCV_SCHEMA)
    if "ohlcv" not in schema.lower():
        raise ValueError(f"{path.name}: schema {schema} is not OHLCV")

    meta = {
        "file": path.name,
        "dataset": str(store.dataset),
        "schema": schema,
        "symbols": list(store.symbols) if store.symbols else [],
        "stype_in": str(store.stype_in) if store.stype_in else None,
        "compression": str(store.compression) if store.compression else None,
    }
    frame = _dataframe_from_store(store)
    if frame is None or frame.empty:
        return {}, meta

    symbol_col = next((c for c in ("symbol", "raw_symbol") if c in frame.columns), None)
    out: dict[str, list[Bar]] = defaultdict(list)
    for ts, row in frame.iterrows():
        bar_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if getattr(bar_ts, "tzinfo", None) is None:
            bar_ts = bar_ts.replace(tzinfo=UTC)
        else:
            bar_ts = bar_ts.astimezone(UTC)
        label = str(row[symbol_col]) if symbol_col else (meta["symbols"][0] if meta["symbols"] else "")
        root = _root_from_symbol_label(label)
        if not root or root not in PRIMARY_RESEARCH_SYMBOLS:
            continue
        out[root].append(
            Bar(
                ts=bar_ts,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=int(row.get("volume", 0)),
            )
        )
    meta["roots_found"] = sorted(out)
    return dict(out), meta


def collect_dbn_paths(directory: Path) -> list[Path]:
    paths: list[Path] = []
    for p in sorted(directory.rglob("*")):
        if not p.is_file():
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
    on_progress: Callable[[str, int], None] | None = None,
) -> list:
    from sqlalchemy import select

    from app.models.instrument import Instrument

    paths = collect_dbn_paths(directory)
    if not paths:
        raise ValueError("No .dbn or .dbn.zst files found")

    grouped: dict[str, list[Bar]] = defaultdict(list)
    file_metas: list[dict] = []
    for i, path in enumerate(paths):
        if on_progress:
            on_progress(f"Decoding {path.name}", 10 + int(50 * i / max(1, len(paths))))
        by_root, meta = bars_by_root_from_dbn(path)
        file_metas.append(meta)
        for root, blist in by_root.items():
            grouped[root].extend(blist)

    created = []
    for root in sorted(grouped):
        blist = sorted({b.ts: b for b in grouped[root]}.values(), key=lambda b: b.ts)
        if not blist:
            continue
        inst = session.execute(select(Instrument).where(Instrument.symbol == root)).scalar_one_or_none()
        if not inst:
            continue
        start = blist[0].ts
        end = blist[-1].ts
        fp = ingest_fingerprint(
            provider_slug="databento",
            instrument_symbol=root,
            timeframe="1m",
            start=start,
            end=end,
        )
        if on_progress:
            on_progress(f"Writing {root} — checking data quality", 65 + 10 * len(created))
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
                "dbn_files": file_metas,
                "price_stitching": False,
                "series_kind": "batch_as_purchased",
                "symbology_note": "Imported from Databento batch DBN; inspect dbn_files for symbology.",
                "continuous_research_only": True,
            },
        )
        tuples = [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in blist]
        write_bars(dataset.id, tuples)
        finalize_dataset_after_write(session, dataset)
        result = validate_and_persist(
            session,
            dataset,
            symbol=root,
            tick_size=inst.tick_size,
            instrument_trading_hours=inst.trading_hours or {},
        )
        qclass = result.get("quality_class", "unknown")
        if on_progress:
            on_progress(f"{root}: quality {qclass}", 80)
        if qclass != "blocked":
            derive_timeframes_from_1m_parent(
                session,
                parent=dataset,
                symbol=root,
                instrument_id=inst.id,
                range_start=start,
                range_end=end,
                tick_size=inst.tick_size,
                trading_hours=inst.trading_hours or {},
                parent_fingerprint=fp,
            )
        created.append(dataset)
    if not created:
        raise ValueError("No MNQ/MES/MGC OHLCV found in files — check symbology in batch metadata")
    if on_progress:
        on_progress("Ready for backtesting", 95)
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

    progress("Downloading your purchased batch", 5)
    staging = batch_staging_root() / str(job_id)
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    download_batch_job_files(job_id, staging)
    progress("Download complete — processing candles", 20)
    datasets = import_dbn_directory(session, staging, source="databento_batch_api", job_id=job_id, on_progress=progress)
    return {"datasets": [str(d.id) for d in datasets], "instrument_symbols": [d.meta.get("instrument_symbol") for d in datasets]}


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
    datasets = import_dbn_directory(session, directory, source="iphone_upload", job_id=None, on_progress=progress)
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
                blob = part.read_bytes()
                out.write(blob)
                part.unlink(missing_ok=True)
        if dest.stat().st_size > int(finfo["size"]) * MAX_EXPAND_RATIO:
            dest.unlink(missing_ok=True)
            raise ValueError(f"File {name} failed integrity check")
        assembled.append(name)
    manifest["completed_at"] = datetime.now(UTC).isoformat()
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return assembled