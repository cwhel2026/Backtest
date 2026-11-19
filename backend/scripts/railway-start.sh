#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-/app}:."

ROLE="${PROP_EDGE_ROLE:-api}"
PORT="${PORT:-8000}"

case "$ROLE" in
  api)
    python -m app.util.db_wait --timeout 25 --migrate-if-ready || echo "[propedge] Migrations deferred; API will retry when Postgres is up."
    exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
    ;;
  worker)
    python -c "from app.services.market_data.storage_backend import ensure_ohlcv_storage; ensure_ohlcv_storage()"
    exec celery -A app.worker.celery_app worker --loglevel=info
    ;;
  beat)
    exec celery -A app.worker.celery_app beat --loglevel=info
    ;;
  *)
    echo "Unknown PROP_EDGE_ROLE=$ROLE (use api, worker, or beat)" >&2
    exit 1
    ;;
esac