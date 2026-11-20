# Railway deployment — PROP EDGE AI 4.1

**Note:** PR #59 (4.0) was still **open** at the start of 4.1 work. Merge **#59** then **#60** (4.1) before expecting scanner tables on production.

## Services

- **Postgres** — plugin or external URL → `DATABASE_URL` / `DATABASE_URL_SYNC`
- **Redis** — plugin → `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- **API** — FastAPI web service
- **Worker** — `celery -A app.worker.celery_app worker`
- **Beat** — `celery -A app.worker.celery_app beat`

## Migrations

Run through **`012`** (scanner + worker health). Startup command should include:

```bash
alembic upgrade head
```

## Health checks

- `GET /api/v1/platform/status` — database, redis, workers, feed
- `GET /api/v1/dashboard/home` — operator summary

## Market data

Default remains **replay** until you configure IBKR or Databento live:

- Historical research: Databento batch ingest (unchanged)
- Forward lab: `LIVE_LAB_PROVIDER=replay` | `event_store` | `ibkr_fixture` | `ibkr_stream`

Do **not** enable paid data subscriptions without explicit approval.

## Integration test (manual)

```bash
docker compose up -d postgres redis
cd backend
export DATABASE_URL_SYNC=postgresql://propedge:propedge_dev@localhost:5432/propedge
alembic upgrade head
LIVE_LAB_INTEGRATION=1 pytest tests/test_live_lab_postgres_e2e.py -v
```

Expect a printed **PASS/FAIL** report; skipped tests are not counted as pass.