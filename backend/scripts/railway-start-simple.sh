#!/usr/bin/env bash
# Easy Railway deploy: API + background worker in ONE service.
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-.}"

PORT="${PORT:-8000}"

echo "[propedge] Waiting for Postgres (will start the API even if it is in recovery)..."
python -m app.util.db_wait --timeout 25 --migrate-if-ready || echo "[propedge] Migrations deferred; API will retry when Postgres is up."

echo "[propedge] Starting background worker (low concurrency for Railway memory)..."
celery -A app.worker.celery_app worker --loglevel=info --pool=solo &

echo "[propedge] Starting scheduler (hourly autonomous research)..."
celery -A app.worker.celery_app beat --loglevel=info &

echo "[propedge] Starting API on port $PORT..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"