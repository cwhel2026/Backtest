from datetime import UTC, datetime, timedelta

from app.services.market_data.dataset_gc import should_reuse_dataset
from app.util.db_errors import DISK_FULL_MESSAGE, compact_error, is_disk_full, set_job_message
from app.util.serde import integrity_hint


class _Job:
    message = ""


def test_should_reuse_fresh_1m_window():
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    assert should_reuse_dataset(
        coverage_start=now - timedelta(days=7),
        coverage_end=now - timedelta(minutes=20),
        row_count=4000,
        window_start=now - timedelta(days=7),
        window_end=now,
        timeframe="1m",
    )


def test_should_not_reuse_stale_or_short():
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    assert not should_reuse_dataset(
        coverage_start=now - timedelta(days=1),
        coverage_end=now - timedelta(days=3),
        row_count=4000,
        window_start=now - timedelta(days=7),
        window_end=now,
        timeframe="1m",
    )
    assert not should_reuse_dataset(
        coverage_start=now - timedelta(days=7),
        coverage_end=now,
        row_count=10,
        window_start=now - timedelta(days=7),
        window_end=now,
        timeframe="1m",
    )


def test_compact_error_strips_sql_params_and_maps_disk_full():
    raw = (
        '(psycopg2.errors.DiskFull) could not extend file "base/16384/16651": No space left on device '
        "HINT: Check free disk space. [SQL: UPDATE research_jobs SET message=%(message)s] "
        "[parameters: {'ts__999': datetime.datetime(2026, 11, 12, 1, 28)}]"
    )
    assert compact_error(raw) == DISK_FULL_MESSAGE
    assert is_disk_full(Exception(raw))


def test_compact_error_truncates_generic():
    assert compact_error("x" * 500) == "x" * 240


def test_integrity_hint_disk_full():
    hint = integrity_hint(Exception("could not extend file: No space left on device"))
    assert hint is not None
    assert "disk" in hint.lower()


def test_set_job_message_clamps_and_rewrites_disk_full():
    job = _Job()
    set_job_message(job, "Loaded MES 1m — " + ("No space left on device " * 20))
    assert job.message == DISK_FULL_MESSAGE
    set_job_message(job, "Scoring NQ 1m · combo ~3/72")
    assert job.message == "Scoring NQ 1m · combo ~3/72"
