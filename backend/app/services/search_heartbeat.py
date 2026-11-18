"""Background heartbeat while prop search runs long CPU-heavy backtests."""

from __future__ import annotations

import threading
import uuid
from typing import Any

from app.db.session import SyncSessionLocal
from app.models.enums import ResearchJobStatus
from app.models.research import ResearchJob
from app.services.search_progress import merge_search_progress
from app.util.db_errors import set_job_message


class SearchJobHeartbeat:
    """Touches job.payload every N seconds so the UI knows the worker is alive."""

    def __init__(self, job_id: uuid.UUID, interval_s: float = 15.0):
        self.job_id = job_id
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.snapshot: dict[str, Any] = {}

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                with SyncSessionLocal() as db:
                    job = db.get(ResearchJob, self.job_id)
                    if not job or job.status != ResearchJobStatus.RUNNING:
                        continue
                    snap = self.snapshot
                    if snap:
                        merge_search_progress(job, **{k: v for k, v in snap.items() if k != "message"})
                        msg = snap.get("message")
                        if isinstance(msg, str) and msg:
                            set_job_message(job, msg)
                    else:
                        merge_search_progress(job, phase="scoring")
                    db.commit()
            except Exception:
                pass

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="prop-search-heartbeat")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def __enter__(self) -> SearchJobHeartbeat:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()