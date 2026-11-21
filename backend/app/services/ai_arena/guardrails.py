"""Global arena emergency stop, spend caps, and cost reservation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Lock

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai_arena import AiApiUsage, AiArenaSettings, AiResearcher

_reservation_lock = Lock()
_reserved_usd: Decimal = Decimal("0")


def get_or_create_settings(session: Session) -> AiArenaSettings:
    row = session.get(AiArenaSettings, 1)
    if row:
        return row
    row = AiArenaSettings(id=1)
    session.add(row)
    session.flush()
    return row


def global_spend_usd(session: Session, *, day: bool = True) -> Decimal:
    since = datetime.now(UTC) - (timedelta(days=1) if day else timedelta(days=31))
    total = session.execute(
        select(func.coalesce(func.sum(AiApiUsage.cost_usd), 0)).where(
            AiApiUsage.created_at >= since,
            AiApiUsage.success.is_(True),
        )
    ).scalar_one()
    return Decimal(str(total or 0)) + _reserved_usd


def arena_globally_allowed(session: Session) -> bool:
    settings = get_or_create_settings(session)
    if settings.emergency_stop:
        return False
    daily = global_spend_usd(session, day=True)
    monthly = global_spend_usd(session, day=False)
    if daily > settings.global_daily_budget_usd:
        return False
    if monthly > settings.global_monthly_budget_usd:
        return False
    return True


ESTIMATED_RESERVE_USD = Decimal("0.05")


def projected_call_budget_usd(_researcher: AiResearcher | None = None) -> Decimal:
    """Conservative reserve before each LLM round (actual billed after response)."""
    return ESTIMATED_RESERVE_USD


def reserve_llm_budget(session: Session, researcher: AiResearcher) -> tuple[bool, str]:
    global _reserved_usd
    settings = get_or_create_settings(session)
    if settings.emergency_stop:
        return False, "Arena emergency stop is active"
    reserve = projected_call_budget_usd(researcher)
    daily = global_spend_usd(session, day=True)
    monthly = global_spend_usd(session, day=False)
    if daily + reserve > settings.global_daily_budget_usd:
        return False, "Global daily AI budget would be exceeded"
    if monthly + reserve > settings.global_monthly_budget_usd:
        return False, "Global monthly AI budget would be exceeded"
    from app.services.ai_arena.budget import spend_usd as researcher_spend

    r_daily = researcher_spend(session, researcher.id, day=True)
    r_monthly = researcher_spend(session, researcher.id, day=False)
    if r_daily + reserve > researcher.daily_budget_usd:
        return False, "Researcher daily budget would be exceeded"
    if r_monthly + reserve > researcher.monthly_budget_usd:
        return False, "Researcher monthly budget would be exceeded"
    with _reservation_lock:
        _reserved_usd += reserve
    return True, ""


def release_llm_reservation() -> None:
    global _reserved_usd
    with _reservation_lock:
        _reserved_usd = max(_reserved_usd - ESTIMATED_RESERVE_USD, Decimal("0"))