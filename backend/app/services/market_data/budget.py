"""Monthly research data download budget (GBP) — estimated / approved / actual USD."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.market_data import ResearchDataBudgetMonth


def month_key(dt: datetime | None = None) -> str:
    ref = dt or datetime.now(UTC)
    return ref.astimezone(UTC).strftime("%Y-%m")


def get_or_create_month(session: Session, key: str | None = None) -> ResearchDataBudgetMonth:
    mk = key or month_key()
    row = session.execute(
        select(ResearchDataBudgetMonth).where(ResearchDataBudgetMonth.month_key == mk)
    ).scalar_one_or_none()
    if row:
        return row
    settings = get_settings()
    row = ResearchDataBudgetMonth(
        month_key=mk,
        budget_gbp=Decimal(str(settings.research_data_budget_gbp)),
    )
    session.add(row)
    session.flush()
    return row


def budget_status(session: Session) -> dict:
    settings = get_settings()
    row = get_or_create_month(session)
    spend_gbp = float(row.approved_usd_to_gbp_equiv(settings.gbp_usd_rate))
    remaining_gbp = float(row.budget_gbp) - spend_gbp
    return {
        "month": row.month_key,
        "budget_gbp": float(row.budget_gbp),
        "estimated_usd": float(row.estimated_usd),
        "approved_usd": float(row.approved_usd),
        "actual_usd": float(row.actual_usd),
        "remaining_budget_gbp": remaining_gbp,
        "gbp_usd_rate": settings.gbp_usd_rate,
        "note": "Approved spend is reserved at ingest request; actual is recorded when download completes.",
    }


def reserve_approval(session: Session, estimated_usd: float, *, allow_over_budget: bool = False) -> None:
    settings = get_settings()
    row = get_or_create_month(session)
    row.estimated_usd = Decimal(str(row.estimated_usd)) + Decimal(str(estimated_usd))
    new_approved = Decimal(str(row.approved_usd)) + Decimal(str(estimated_usd))
    rate = settings.gbp_usd_rate
    if rate and rate > 0:
        spend_gbp = float(new_approved) / rate
        if spend_gbp > float(row.budget_gbp) + 1e-6 and not allow_over_budget:
            raise ValueError(
                f"Monthly research data budget exceeded (£{row.budget_gbp:.2f}). "
                "Pass budget_override=true for one-off approval."
            )
    row.approved_usd = new_approved
    session.flush()


def record_actual_spend(session: Session, actual_usd: float) -> None:
    row = get_or_create_month(session)
    row.actual_usd = Decimal(str(row.actual_usd)) + Decimal(str(actual_usd))
    session.flush()