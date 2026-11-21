#!/usr/bin/env bash
# Easy Railway deploy: API + background worker in ONE service.
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-.}"

PORT="${PORT:-8000}"

echo "[propedge] Waiting for Postgres (will start the API even if it is in recovery)..."
python -m app.util.db_wait --timeout 25 --migrate-if-ready || echo "[propedge] Migrations deferred; API will retry when Postgres is up."

echo "[propedge] OHLCV storage bootstrap..."
python -c "from app.services.market_data.storage_backend import ensure_ohlcv_storage; print(ensure_ohlcv_storage())"

echo "[propedge] Starting realtime worker (stream ingest / paper tick)..."
celery -A app.worker.celery_app worker --loglevel=info --pool=solo -Q realtime -n realtime@%h &

echo "[propedge] Starting research worker (backtests / ingestion / search)..."
celery -A app.worker.celery_app worker --loglevel=info --pool=solo -Q research -n research@%h &

echo "[propedge] Starting AI arena worker (LLM research cycles)..."
celery -A app.worker.celery_app worker --loglevel=info --pool=solo -Q ai_arena -n ai_arena@%h &

echo "[propedge] Starting scheduler..."
celery -A app.worker.celery_app beat --loglevel=info &

echo "[propedge] Starting API on port $PORT..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"