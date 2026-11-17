import uuid
from unittest.mock import MagicMock

from app.models.enums import ResearchJobKind, ResearchJobStatus
from app.models.research import ResearchJob
from app.services.autonomous_cycle import PROP_SEARCH_JOB_TITLE
from app.services.research_jobs import add_job_with_activity


def test_add_job_with_activity_flushes_job_before_activity():
    job = ResearchJob(
        id=uuid.uuid4(),
        kind=ResearchJobKind.VALIDATION,
        status=ResearchJobStatus.QUEUED,
        title=PROP_SEARCH_JOB_TITLE,
        message="q",
        payload={},
    )
    session = MagicMock()
    add_job_with_activity(session, job, headline="h", detail="d")
    # Job insert must be flushed before activity references job_id.
    session.flush.assert_called_once()
    session.add.assert_called()