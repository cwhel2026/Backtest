import uuid
from unittest.mock import MagicMock, patch

from app.core.config import get_settings
from app.models.enums import ResearchJobKind, ResearchJobStatus
from app.models.research import ResearchJob
from app.services.autonomous_cycle import PROP_SEARCH_JOB_TITLE
from app.worker.tasks import autonomous_prop_cycle, run_prop_search_job


def test_manual_search_task_does_not_require_hourly_flag(monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_HOURLY_ENABLED", "false")
    get_settings.cache_clear()
    job_id = str(uuid.uuid4())
    called: list[str] = []

    job = ResearchJob(
        id=uuid.UUID(job_id),
        kind=ResearchJobKind.VALIDATION,
        status=ResearchJobStatus.QUEUED,
        title=PROP_SEARCH_JOB_TITLE,
        message="queued",
        payload={"actor": "user@test"},
    )

    def fake_cycle(db, actor="autopilot", job_id=None):
        called.append(actor)

    mock_db = MagicMock()
    mock_db.get.return_value = job

    with patch("app.worker.tasks.SyncSession") as mock_session:
        mock_session.return_value.__enter__.return_value = mock_db
        with patch("app.worker.tasks.run_autonomous_prop_cycle", side_effect=fake_cycle):
            run_prop_search_job(job_id)

    assert called == ["user@test"]
    get_settings.cache_clear()


def test_hourly_cycle_skips_when_hourly_disabled(monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_HOURLY_ENABLED", "false")
    get_settings.cache_clear()
    with patch("app.worker.tasks.run_autonomous_prop_cycle") as mock_cycle:
        autonomous_prop_cycle()
        mock_cycle.assert_not_called()
    get_settings.cache_clear()


def test_hourly_cycle_skips_when_manual_job_active(monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_HOURLY_ENABLED", "true")
    get_settings.cache_clear()
    mock_db = MagicMock()
    with patch("app.worker.tasks.SyncSession") as mock_session:
        mock_session.return_value.__enter__.return_value = mock_db
        with patch("app.worker.tasks.find_active_prop_search_job", return_value=object()):
            with patch("app.worker.tasks.run_autonomous_prop_cycle") as mock_cycle:
                autonomous_prop_cycle()
                mock_cycle.assert_not_called()
    get_settings.cache_clear()