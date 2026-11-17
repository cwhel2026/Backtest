#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-/app}:."

ROLE="${PROP_EDGE_ROLE:-api}"
PORT="${PORT:-8000}"

case "$ROLE" in
  api)
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
    ;;
  worker)
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