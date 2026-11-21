"""Per-researcher API spend caps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai_arena import AiApiUsage, AiResearcher


def spend_usd(session: Session, researcher_id, *, day: bool = True) -> Decimal:
    since = datetime.now(UTC) - (timedelta(days=1) if day else timedelta(days=31))
    total = session.execute(
        select(func.coalesce(func.sum(AiApiUsage.cost_usd), 0)).where(
            AiApiUsage.researcher_id == researcher_id,
            AiApiUsage.created_at >= since,
            AiApiUsage.success.is_(True),
        )
    ).scalar_one()
    return Decimal(str(total or 0))


def budget_allows(session: Session, researcher: AiResearcher) -> tuple[bool, str]:
    daily = spend_usd(session, researcher.id, day=True)
    monthly = spend_usd(session, researcher.id, day=False)
    if daily >= researcher.daily_budget_usd:
        return False, f"Daily AI budget exceeded ({daily:.4f} / {researcher.daily_budget_usd} USD)"
    if monthly >= researcher.monthly_budget_usd:
        return False, f"Monthly AI budget exceeded ({monthly:.4f} / {researcher.monthly_budget_usd} USD)"
    return True, ""