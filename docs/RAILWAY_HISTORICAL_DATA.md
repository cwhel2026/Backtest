# Railway — Historical Data Engine 3.0 (persistent OHLCV)

**You must configure this manually in the Railway dashboard.** This document does not change your production variables.

## Goal

Parquet OHLCV lives on a **persistent volume**, not the container filesystem. Postgres holds dataset metadata, checksums, `storage_uri`, and version tags. Redeploys must not delete imported history.

---

## Option A — Single backend service (API + Celery worker in one container)

Recommended in [RAILWAY_EASY.md](./RAILWAY_EASY.md). One volume serves API and worker.

### 1. Create a volume

1. Open your **backend** service in Railway.
2. **Volumes** → **Add volume**.
3. **Mount path:** `/data`  
4. Size: start at **5–20 GB** (grow with 1m history).

### 2. Set variables (backend service)

| Variable | Value |
|----------|--------|
| `OHLCV_STORE_DIR` | `/data/ohlcv` |
| `OHLCV_PERSISTENT_REQUIRED` | `true` |

If `OHLCV_STORE_DIR` is omitted on Railway and `/data` exists, the app auto-selects `/data/ohlcv`.

### 3. Run migrations

Backend start script runs Alembic when Postgres is up. Ensure migration **007** (`storage_uri`) is applied:

```bash
alembic upgrade head
```

### 4. Verify

Open **Historical Data** → **Engine health**:

- `persistent_ok: true`
- `resolved_path` → `/data/ohlcv`
- `railway_volume_mounted: true`

---

## Option B — Split API and worker services

Railway volumes attach to **one** service. Workers on another service **do not** see the same disk.

Use **S3-compatible mirror** (AWS S3, Cloudflare R2, MinIO, etc.) on **both** API and worker:

| Variable | API | Worker |
|----------|-----|--------|
| `OHLCV_STORE_DIR` | `/data/ohlcv` (optional local cache) | same |
| `OHLCV_S3_BUCKET` | same bucket | same bucket |
| `OHLCV_S3_ENDPOINT` | e.g. `https://<account>.r2.cloudflarestorage.com` | same |
| `OHLCV_S3_ACCESS_KEY` | key | same |
| `OHLCV_S3_SECRET_KEY` | secret | same |
| `OHLCV_S3_REGION` | `auto` or region | same |
| `PROP_EDGE_ROLE` | `api` | `worker` |

After each ingest, parquet shards upload to `s3://<bucket>/ohlcv/<dataset_id>/`. Workers/backtests **hydrate** from S3 when local files are missing.

---

## What the application does automatically

- Creates `OHLCV_STORE_DIR` (and per-dataset folders) on startup.
- Writes `storage_uri` on each dataset (`file://...` plus `s3://...` when mirrored).
- Blocks treating repo-local `data/ohlcv` as production storage when `OHLCV_PERSISTENT_REQUIRED=true` on Railway.
- Logs an error on startup if Railway has no `/data` mount and no S3 mirror.

---

## Postgres metadata (survives redeploy)

`historical_datasets` stores:

- `version_tag`, `content_checksum`, `storage_uri`
- `coverage_*`, `row_count`, `meta` (quality class, rollover, provider)

Parquet bytes are **not** in Postgres.

---

## Checklist after deploy

1. Volume mounted at `/data` (Option A) or S3 vars on all bar-touching services (Option B).
2. `OHLCV_STORE_DIR=/data/ohlcv`.
3. Alembic at head (including 006 budget, 007 `storage_uri`).
4. Historical Data health: writable + persistent (or S3 ok).
5. Run a small Yahoo/CSV ingest, redeploy, confirm dataset row count unchanged and chart preview still loads.

---

## Do not

- Store production OHLCV only under `data/ohlcv` inside the image (ephemeral).
- Rely on Postgres `ohlcv_bars` for large 1m history (legacy path only).