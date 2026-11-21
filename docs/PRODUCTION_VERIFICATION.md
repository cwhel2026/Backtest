# Production verification (Railway)

## Authenticated API

After login, call:

- `GET /api/v1/platform/status` — workers, feed, **CME session clock**, storage root
- `GET /api/v1/platform/deployment-audit` — datasets on volume, lineage, alembic revision, worker `detail`, **Databento get_cost only** (no download)

## Log expectations (post repair)

Worker logs include structured lines:

```
live_lab_stream_ingest {"events": 0, "idle_reason": "...", "work_done": false}
paper_forward_tick {"opened": 0, "closed": 0, "active_slots": N, "idle_reason": "..."}
```

Celery **succeeded: None** only means the task did not crash — use beats or logs above for work done.

## Manual bounded research

`POST /api/v1/autopilot/run?budget_per_symbol=24&history_days=14` queues on **research** queue (isolated from 5s ingest).

## Databento

Deployment audit calls `metadata.get_cost` for 24h MES window when `DATABENTO_API_KEY` is set — **no `get_range`**. Approve paid downloads only via Market Data UI.

## Celery isolation

`railway-start-simple.sh` runs two solo workers: `realtime` and `research`. Long backtests cannot block `live_lab_stream_ingest`.

## Saturday / market closed

`cme_session.session_day=false` is normal. Historical backtests and replay still run on stored parquet.

## Restart persistence

Confirm `deployment-audit.datasets.*.on_disk` and `storage_bootstrap.store_path` under `/data/ohlcv` after redeploy.