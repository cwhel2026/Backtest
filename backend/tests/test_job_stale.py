from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.models.enums import ResearchJobStatus
from app.services.autonomous_cycle import job_is_stale


def test_queued_job_not_stale_within_claim_window():
    now = datetime.now(UTC)
    job = SimpleNamespace(
        status=ResearchJobStatus.QUEUED,
        created_at=now - timedelta(minutes=5),
        started_at=None,
        payload={},
    )
    assert not job_is_stale(job, now)


def test_queued_job_stale_after_long_wait():
    now = datetime.now(UTC)
    job = SimpleNamespace(
        status=ResearchJobStatus.QUEUED,
        created_at=now - timedelta(minutes=20),
        started_at=None,
        payload={},
    )
    assert job_is_stale(job, now)