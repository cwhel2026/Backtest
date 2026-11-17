#!/usr/bin/env bash
# Easy Railway deploy: API + background worker in ONE service.
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-.}"

PORT="${PORT:-8000}"

echo "[propedge] Running database migrations..."
alembic upgrade head

echo "[propedge] Starting background worker (low concurrency for Railway memory)..."
celery -A app.worker.celery_app worker --loglevel=info --pool=solo &

echo "[propedge] Starting API on port $PORT..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"