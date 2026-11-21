# Railway OHLCV persistence (required for production)

## Symptom

Logs show `ohlcv_ephemeral_railway` with advice to mount `/data`.

## Root cause

API and worker containers use **separate filesystems**. Parquet files written on one service are invisible on the other. Without a shared volume (or S3 mirror), historical datasets survive only until the container restarts.

## Fix (recommended)

1. In Railway, create a **Volume** and mount it at **`/data`** on **every** service that reads/writes OHLCV:
   - `backend` (API)
   - `worker`
   - `beat` (optional; only if it touches parquet — usually not)

2. Set environment variables on **API and worker** (identical values):
   ```
   OHLCV_STORE_DIR=/data/ohlcv
   OHLCV_PERSISTENT_REQUIRED=true
   ```

3. Redeploy. On boot, `ensure_ohlcv_storage()` synchronizes the in-process store path and logs `store_path` without crashing startup.

## Alternative: S3 mirror

If you cannot use a volume, configure:

```
OHLCV_S3_BUCKET=...
OHLCV_S3_ACCESS_KEY=...
OHLCV_S3_SECRET_KEY=...
OHLCV_S3_REGION=...
```

The worker writes parquet locally and mirrors to S3; the API hydrates from S3 when local files are missing (`hydrate_dataset_from_remote`).

## Do not

- Delete existing dataset rows in Postgres — metadata remains; restore parquet from volume backup or S3.
- Point API and worker at different `OHLCV_STORE_DIR` values.