"""Persist Celery worker heartbeats — distinct from market feed pause state."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.scanner import WorkerHealthBeat


def record_worker_beat(
    session: Session,
    worker_name: str,
    *,
    success: bool,
    stale_after_seconds: int = 600,
    detail: dict | None = None,
) -> WorkerHealthBeat:
    now = datetime.now(UTC)
    row = session.get(WorkerHealthBeat, worker_name)
    if not row:
        row = WorkerHealthBeat(
            worker_name=worker_name,
            last_success_at=now if success else None,
            last_attempt_at=now,
            stale_after_seconds=stale_after_seconds,
            detail=detail or {},
        )
        session.add(row)
        return row
    row.last_attempt_at = now
    if success:
        row.last_success_at = now
    if detail:
        merged = dict(row.detail or {})
        merged.update(detail)
        row.detail = merged
    row.stale_after_seconds = stale_after_seconds
    return row


def worker_is_stale(row: WorkerHealthBeat | None, *, now: datetime | None = None) -> bool:
    if not row or not row.last_success_at:
        return True
    ref = now or datetime.now(UTC)
    age = (ref - row.last_success_at).total_seconds()
    return age > row.stale_after_seconds