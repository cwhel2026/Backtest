"""Recover interrupted arena cycles and prevent duplicate workers."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.ai_arena import AiResearchCycle, AiResearcher

STALE_MINUTES = 90


def recover_stale_cycles(session: Session, researcher_id) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=STALE_MINUTES)
    stale = session.execute(
        select(AiResearchCycle).where(
            AiResearchCycle.researcher_id == researcher_id,
            AiResearchCycle.status == "running",
            AiResearchCycle.started_at < cutoff,
        )
    ).scalars().all()
    for row in stale:
        row.status = "interrupted"
        row.error = "Recovered stale cycle after worker restart or timeout"
        row.completed_at = datetime.now(UTC)
    return len(stale)


def cycle_already_running(session: Session, researcher_id) -> bool:
    row = session.execute(
        select(AiResearchCycle)
        .where(AiResearchCycle.researcher_id == researcher_id, AiResearchCycle.status == "running")
        .limit(1)
    ).scalar_one_or_none()
    if not row:
        return False
    hb = row.heartbeat_at or row.started_at
    if hb and hb < datetime.now(UTC) - timedelta(minutes=STALE_MINUTES):
        recover_stale_cycles(session, researcher_id)
        return False
    return True


def mint_worker_token(cycle: AiResearchCycle) -> str:
    token = secrets.token_hex(16)
    cycle.worker_token = token
    cycle.heartbeat_at = datetime.now(UTC)
    return token


def touch_cycle_heartbeat(session: Session, cycle_id, token: str) -> bool:
    row = session.get(AiResearchCycle, cycle_id)
    if not row or row.worker_token != token or row.status != "running":
        return False
    row.heartbeat_at = datetime.now(UTC)
    session.add(row)
    return True