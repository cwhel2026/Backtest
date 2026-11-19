"""PostgreSQL + Celery integration — skipped unless LIVE_LAB_INTEGRATION=1."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_LAB_INTEGRATION") != "1",
    reason="Set LIVE_LAB_INTEGRATION=1 with docker compose up postgres redis worker",
)


def test_postgres_celery_forward_acceptance():
    """Full workflow: fixture ingest, forward run, worker tick, restart, ledger compare.

    Run:
      docker compose up -d postgres redis worker
      cd backend && LIVE_LAB_INTEGRATION=1 pytest tests/test_live_lab_postgres_e2e.py -v
    """
    assert False, "Implement in CI — scaffold documents required command"