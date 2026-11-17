# Deploy PROP EDGE AI on Railway (GitHub-connected)

Railway runs the platform **24/7** as separate services from one GitHub repo: API, Celery worker, Celery beat, frontend, plus managed Postgres and Redis.

## 1. Create the Railway project

1. [Railway](https://railway.com) → **New Project** → **Deploy from GitHub repo** → select `Backtest`.
2. Add **PostgreSQL** and **Redis** to the project (Database → **Add**).

## 2. Shared variables (project or per-service)

Set these on **API**, **worker**, and **beat** (use Railway **Shared Variables** or reference plugin URLs):

| Variable | Value |
|----------|--------|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference from Postgres service) |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` |
| `SECRET_KEY` | long random string (required in production) |
| `INITIAL_ADMIN_EMAIL` | your email |
| `INITIAL_ADMIN_PASSWORD` | strong password |
| `ENVIRONMENT` | `production` |
| `ALLOWED_ORIGINS` | `https://YOUR-FRONTEND.up.railway.app` (after frontend gets a domain) |

Optional: `DATABENTO_API_KEY`, `OPENAI_API_KEY`, `AI_RESEARCH_ENABLED=true`.

Celery broker URLs are **derived from `REDIS_URL`** when not set (suited to a single Railway Redis).

## 3. Backend API service

1. **New Service** → same GitHub repo.
2. **Settings → Root Directory**: `backend`
3. **Settings → Config file**: `railway.api.toml`
4. **Variables**: `PROP_EDGE_ROLE=api` (optional; default in start script is `api`)
5. Link **Postgres** and **Redis** variables as above.
6. **Networking → Generate domain** (e.g. `propedge-api.up.railway.app`).

Railway sets `PORT`; the start script runs `alembic upgrade head` then Uvicorn.

## 4. Celery worker service

1. Duplicate the backend service or create another from the same repo.
2. Root Directory: `backend`
3. Config file: `railway.worker.toml`
4. Same `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY` as API (no public domain required).
5. **Do not** enable HTTP health checks on this service (no HTTP server).

## 5. Celery beat service (optional)

Same as worker but config file `railway.beat.toml` (scheduler for research heartbeat / future jobs).

## 6. Frontend service

1. **New Service** → same repo.
2. Root Directory: `frontend`
3. Config file: `railway.toml`
4. **Build-time variable** (required for Next.js):

   `NEXT_PUBLIC_API_URL=https://YOUR-API.up.railway.app`

5. Generate a **public domain** for the frontend.
6. Update API `ALLOWED_ORIGINS` to include the frontend URL (comma-separated). Redeploy API.

## 7. Verify

| Check | URL |
|-------|-----|
| API health | `https://YOUR-API.up.railway.app/health` |
| OpenAPI | `https://YOUR-API.up.railway.app/docs` |
| Dashboard | `https://YOUR-FRONTEND.up.railway.app` |

Sign in with `INITIAL_ADMIN_*`. Import CSV on **Market Data**, queue a backtest on **Backtest Laboratory** (worker must be running).

## 8. Branch deploys

Railway can deploy `main` or PR branches. Use the same layout for staging; point `ALLOWED_ORIGINS` and `NEXT_PUBLIC_API_URL` at staging domains.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| API 502 on boot | Check deploy logs for Alembic/DB connection; confirm `DATABASE_URL` reference |
| CORS errors | Add exact frontend origin to `ALLOWED_ORIGINS` on API |
| Backtests stuck queued | Worker service running? Shared `REDIS_URL`? |
| Login works locally only | `SECRET_KEY` must match across services; cookies are origin-specific |

## Docker alternative

You can deploy each service with **Dockerfile** instead of Nixpacks: set builder to Dockerfile and use `backend/Dockerfile` with `startCommand` from `scripts/railway-start.sh`.