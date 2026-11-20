"""Aggregated AI research centre — validated metrics only."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.enums import ResearchJobStatus
from app.models.research import ResearchJob
from app.services.leaderboard import leaderboard_entries_sync


def build_research_centre(session: Session, *, limit: int = 40) -> dict:
    jobs = session.execute(select(ResearchJob).order_by(desc(ResearchJob.created_at)).limit(30)).scalars().all()
    leaderboard = leaderboard_entries_sync(session, limit=limit, profitable_only=False)
    validated = [e for e in leaderboard if e.get("passes_prop_screen")]
    rejected = [e for e in leaderboard if not e.get("passes_prop_screen")]

    running = [j for j in jobs if j.status in (ResearchJobStatus.RUNNING, ResearchJobStatus.QUEUED)]

    def job_card(j: ResearchJob) -> dict:
        return {
            "id": str(j.id),
            "title": j.title,
            "kind": j.kind.value if hasattr(j.kind, "value") else str(j.kind),
            "status": j.status.value if hasattr(j.status, "value") else str(j.status),
            "message": j.message,
            "progress_pct": j.progress_pct or 0,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }

    return {
        "disclaimer": "Rankings use historical backtest evidence. Paper-forward and live results are labelled separately. Low trade counts are not marketed as profitable.",
        "active_jobs": [job_card(j) for j in running],
        "recent_jobs": [job_card(j) for j in jobs[:15]],
        "leaderboard": leaderboard,
        "validated_candidates": validated[:20],
        "rejected_candidates": rejected[:15],
        "summary": {
            "tests_completed": len(leaderboard),
            "validated_count": len(validated),
            "rejected_count": len(rejected),
            "active_experiments": len(running),
        },
    }