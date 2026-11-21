"""Suspend arena paper slots on risk breach or forward deterioration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.paper import PaperFill, PaperSlot


def monitor_arena_paper_slots(session: Session, *, min_closed_trades: int = 5) -> dict:
    suspended = []
    slots = [
        s
        for s in session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()
        if s.arena_attribution
    ]
    for slot in slots:
        fills = session.execute(
            select(PaperFill).where(PaperFill.slot_id == slot.id).order_by(PaperFill.exit_ts.desc())
        ).scalars().all()
        if len(fills) < min_closed_trades:
            continue
        recent = fills[: min_closed_trades]
        net = sum(Decimal(str(f.net_pnl)) for f in recent)
        if net < Decimal("-400"):
            slot.status = "suspended"
            slot.last_error = f"Arena forward deterioration: last {len(recent)} trades net {net}"
            session.add(slot)
            suspended.append(str(slot.id))
    return {"suspended": suspended, "checked": len(slots)}