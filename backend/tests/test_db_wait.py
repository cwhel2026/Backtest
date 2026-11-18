import subprocess

from app.util.db_errors import POSTGRES_RECOVERY_MESSAGE, compact_error
from app.util.db_wait import is_retryable_db, wait_for_postgres


SQLALCHEMY_RECOVERY = (
    'sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) '
    'connection to server at "postgres.railway.internal" '
    "(fd12:327:6cad:1:5000:a2:bf31:7d2b), port 5432 failed: FATAL:  "
    "the database system is in recovery mode "
    "(Background on this error at: https://sqlalche.me/e/20"
)


def test_sqlalchemy_recovery_traceback_is_retryable():
    assert is_retryable_db(SQLALCHEMY_RECOVERY)
    assert is_retryable_db(Exception(SQLALCHEMY_RECOVERY))
    assert compact_error(SQLALCHEMY_RECOVERY) == POSTGRES_RECOVERY_MESSAGE


def test_wait_succeeds_after_recovery():
    calls = {"n": 0}

    def probe() -> bool:
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("the database system is in recovery mode")
        return True

    assert wait_for_postgres(timeout_seconds=2, interval_seconds=0.001, probe=probe)
    assert calls["n"] == 3


def test_wait_times_out_while_recovering():
    def probe() -> bool:
        raise Exception("the database system is in recovery mode")

    assert wait_for_postgres(timeout_seconds=0.02, interval_seconds=0.005, probe=probe) is False


def test_alembic_calledprocesserror_stderr_is_retryable():
    err = subprocess.CalledProcessError(
        1,
        ["alembic", "upgrade", "head"],
        output="",
        stderr="FATAL:  the database system is in recovery mode",
    )
    assert is_retryable_db(err)
    assert compact_error(err) == POSTGRES_RECOVERY_MESSAGE


def test_non_retryable_probe_raises():
    def probe() -> bool:
        raise RuntimeError("syntax error at or near")

    try:
        wait_for_postgres(timeout_seconds=1, interval_seconds=0.001, probe=probe)
    except RuntimeError as exc:
        assert "syntax error" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
