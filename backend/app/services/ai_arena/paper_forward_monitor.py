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
            attr = slot.arena_attribution or {}
            rid = attr.get("researcher_id")
            if rid:
                from uuid import UUID

                from app.models.ai_arena import AiResearcher

                researcher = session.get(AiResearcher, UUID(str(rid)))
                if researcher:
                    mem = dict(researcher.memory or {})
                    fd = mem.get("forward_deterioration") or []
                    fd.append({"slot_id": str(slot.id), "net": float(net), "trades": len(recent)})
                    mem["forward_deterioration"] = fd[-10:]
                    researcher.memory = mem
                    session.add(researcher)
    return {"suspended": suspended, "checked": len(slots)}