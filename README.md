# PROP EDGE AI

Autonomous AI futures strategy research, backtesting, tracking and prop-firm trading platform (private).

This repository implements **Phase 1 (Foundation)**: database, authentication, instrument registry, market data framework, background workers, and the research dashboard. No fabricated market data or backtest results are shown.

## Quick start (Docker)

**Requirements:** Docker and Docker Compose.

```bash
cp .env.example .env
# Edit .env — at minimum change SECRET_KEY and INITIAL_ADMIN_PASSWORD
docker compose up --build
```

| Service   | URL |
|-----------|-----|
| Dashboard | http://localhost:3000 |
| API       | http://localhost:8000 |
| API docs  | http://localhost:8000/docs |

**Default admin** (first API boot, if no users exist):

- Email: value of `INITIAL_ADMIN_EMAIL` (default `admin@propedge.local`)
- Password: value of `INITIAL_ADMIN_PASSWORD` in `.env`

## Local development (without full Docker)

### Database & Redis

```bash
docker compose up postgres redis -d
cp .env.example .env
```

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

In another terminal:

```bash
cd backend && source .venv/bin/activate
celery -A app.worker.celery_app worker --loglevel=info
```

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

### Tests

```bash
cd backend && source .venv/bin/activate && pytest
```

## Market data

Set `DATABENTO_API_KEY` in `.env` after obtaining a licensed Databento account. Until the Phase 1.5 ingestion implementation lands, jobs are queued and recorded but **do not import bars** without a connected provider.

## Project status

See [PROGRESS.md](./PROGRESS.md) for completed work and next steps.

## Architecture (Phase 1)

```
frontend (Next.js) ──HTTP/JWT──► backend (FastAPI)
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
              PostgreSQL          Redis            Celery worker
```

Licensed futures data and AI research run **only** when you configure credentials server-side.