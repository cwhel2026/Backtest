"""Wait out Postgres crash recovery so Railway boot does not 502."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from app.util.db_errors import (
    POSTGRES_RECOVERY_MESSAGE,
    compact_error,
    is_disk_full,
    is_disk_full_text,
    is_postgres_recovery,
)

RETRYABLE_SNIPPETS = (
    "connection refused",
    "connection reset",
    "could not connect",
    "timeout expired",
    "server closed the connection",
    "the database system is starting up",
    "too many connections",
    "temporarily down",
)


def is_retryable_db(exc: BaseException | str) -> bool:
    if not isinstance(exc, str) and (is_postgres_recovery(exc) or is_disk_full(exc)):
        return True
    text = f"{exc} {getattr(exc, 'orig', '')}".lower() if not isinstance(exc, str) else exc.lower()
    return is_postgres_recovery(text) or is_disk_full_text(text) or any(s in text for s in RETRYABLE_SNIPPETS)


def probe_postgres() -> bool:
    from sqlalchemy import create_engine, text

    from app.core.config import get_settings

    engine = create_engine(
        get_settings().database_url_sync,
        pool_pre_ping=False,
        pool_size=1,
        max_overflow=0,
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    finally:
        engine.dispose()


def wait_for_postgres(
    *,
    timeout_seconds: float = 30,
    interval_seconds: float = 2,
    probe: Callable[[], bool] | None = None,
) -> bool:
    check = probe or probe_postgres
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            if check():
                return True
        except Exception as exc:
            if not is_retryable_db(exc):
                raise
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_seconds)


def alembic_ini() -> Path:
    return Path(__file__).resolve().parents[2] / "alembic.ini"


def run_alembic_upgrade() -> None:
    ini = alembic_ini()
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), "upgrade", "head"],
        cwd=str(ini.parent),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--migrate-if-ready", action="store_true")
    args = parser.parse_args(argv)
    print("[propedge] Waiting for Postgres…", flush=True)
    try:
        ready = wait_for_postgres(timeout_seconds=args.timeout)
    except Exception as exc:
        print(f"[propedge] Database probe failed: {compact_error(exc)}", flush=True)
        return 1
    if not ready:
        print(f"[propedge] {POSTGRES_RECOVERY_MESSAGE}", flush=True)
        print("[propedge] Starting the API anyway so /health and login can explain this.", flush=True)
        return 0
    if args.migrate_if_ready:
        print("[propedge] Running database migrations…", flush=True)
        run_alembic_upgrade()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
