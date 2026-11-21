"""Aggregate forward paper performance per arena researcher."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_arena import AiResearcher
from app.models.paper import PaperFill, PaperSlot


def paper_stats_for_researcher(session: Session, researcher: AiResearcher) -> dict:
    provider = researcher.provider_slug
    slots = session.execute(select(PaperSlot)).scalars().all()
    mine = [s for s in slots if (s.arena_attribution or {}).get("ai_provider") == provider]
    active = [s for s in mine if s.status == "active"]
    fills: list[PaperFill] = []
    for slot in mine:
        fills.extend(session.execute(select(PaperFill).where(PaperFill.slot_id == slot.id)).scalars().all())
    if not fills:
        return {
            "active_forward_strategies": len(active),
            "closed_paper_trades": 0,
            "paper_net_pnl": 0.0,
            "paper_win_rate": None,
            "paper_profit_factor": None,
            "paper_max_drawdown": 0.0,
            "insufficient_sample": True,
        }
    nets = [Decimal(str(f.net_pnl)) for f in fills]
    wins = [n for n in nets if n > 0]
    losses = [abs(n) for n in nets if n < 0]
    gross_win = sum(wins, Decimal(0))
    gross_loss = sum(losses, Decimal(0)) or Decimal("1")
    equity = Decimal(0)
    peak = Decimal(0)
    max_dd = Decimal(0)
    for n in nets:
        equity += n
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "active_forward_strategies": len(active),
        "closed_paper_trades": len(fills),
        "paper_net_pnl": float(equity),
        "paper_win_rate": float(len(wins) / len(nets)) if nets else None,
        "paper_profit_factor": float(gross_win / gross_loss) if gross_loss else None,
        "paper_max_drawdown": float(max_dd),
        "insufficient_sample": len(fills) < 5,
    }