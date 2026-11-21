"""Ensure one AiResearcher row per provider slug."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_arena import PROVIDER_SLUGS, AiResearcher
from app.services.ai_arena.llm_providers import PROVIDER_DEFS, build_provider, list_provider_catalog


def ensure_ai_researchers(session: Session) -> list[AiResearcher]:
    catalog = {c["slug"]: c for c in list_provider_catalog()}
    rows: list[AiResearcher] = []
    for slug in PROVIDER_SLUGS:
        row = session.execute(select(AiResearcher).where(AiResearcher.provider_slug == slug)).scalar_one_or_none()
        meta = next((d for d in PROVIDER_DEFS if d["slug"] == slug), None)
        display = catalog.get(slug, {}).get("display_name") or slug.title()
        default_model = catalog.get(slug, {}).get("default_model") or ""
        if not row:
            row = AiResearcher(
                provider_slug=slug,
                display_name=display,
                model_id=default_model,
                enabled=False,
                activated_by_user=False,
                connection_status="unconfigured",
                objectives={
                    "symbols": ["MNQ", "MES", "MGC"],
                    "families": [
                        "momentum",
                        "mean_reversion",
                        "liquidity_sweep",
                        "trend_following",
                        "breakout",
                        "volatility",
                        "volume",
                        "market_structure",
                    ],
                    "prop_constraints": {
                        "daily_loss_usd": 2000,
                        "trailing_drawdown_usd": 3000,
                        "profit_target_usd": 6000,
                    },
                },
            )
            session.add(row)
            session.flush()
        else:
            if not row.model_id and default_model:
                row.model_id = default_model
        prov = build_provider(slug)
        if prov and prov.api_key_configured():
            row.connection_status = "configured"
        elif not prov or not prov.api_key_configured():
            if row.connection_status not in ("connected", "error"):
                row.connection_status = "unconfigured"
        rows.append(row)
    session.flush()
    return rows