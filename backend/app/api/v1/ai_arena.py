"""AI Research Arena API — settings without exposing API keys."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import SyncSessionLocal, get_db
from app.models.ai_arena import AiResearcher
from app.models.user import User
from app.services.ai_arena.arena_dashboard import build_arena_dashboard, researcher_detail
from app.services.ai_arena.bootstrap import ensure_ai_researchers
from app.services.ai_arena.llm_providers import build_provider, list_provider_catalog
from app.worker.tasks import ai_researcher_cycle_task

router = APIRouter(prefix="/ai-arena", tags=["ai-arena"])


class ResearcherSettingsPatch(BaseModel):
    enabled: bool | None = None
    activated_by_user: bool | None = None
    model_id: str | None = Field(None, max_length=128)
    research_frequency_minutes: int | None = Field(None, ge=15, le=24 * 60)
    daily_budget_usd: float | None = Field(None, ge=0, le=500)
    monthly_budget_usd: float | None = Field(None, ge=0, le=5000)
    max_concurrent_experiments: int | None = Field(None, ge=1, le=8)


@router.get("")
async def arena_dashboard(_: User = Depends(get_current_user)) -> dict:
    with SyncSessionLocal() as session:
        return build_arena_dashboard(session)


@router.get("/researchers/{slug}")
async def arena_researcher(slug: str, _: User = Depends(get_current_user)) -> dict:
    with SyncSessionLocal() as session:
        try:
            return researcher_detail(session, slug)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc


@router.get("/providers")
async def provider_catalog(_: User = Depends(get_current_user)) -> dict:
    return {"providers": list_provider_catalog()}


@router.patch("/researchers/{slug}/settings")
async def patch_researcher_settings(
    slug: str,
    body: ResearcherSettingsPatch,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    with SyncSessionLocal() as session:
        row = session.execute(select(AiResearcher).where(AiResearcher.provider_slug == slug)).scalar_one_or_none()
        if not row:
            raise HTTPException(404, "Researcher not found")
        data = body.model_dump(exclude_unset=True)
        if "enabled" in data and data["enabled"] and not row.activated_by_user:
            raise HTTPException(400, "Activate researcher first (explicit user consent after key is configured).")
        if "activated_by_user" in data and data["activated_by_user"]:
            prov = build_provider(slug)
            if not prov or not prov.api_key_configured():
                raise HTTPException(400, f"Configure {slug} API key in Railway/env before activation.")
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = datetime.now(UTC)
        session.commit()
        return {"ok": True, "provider_slug": slug, "enabled": row.enabled, "activated_by_user": row.activated_by_user}


@router.post("/researchers/{slug}/test-connection")
async def test_connection(slug: str, _: User = Depends(get_current_user)) -> dict:
    prov = build_provider(slug)
    if not prov:
        raise HTTPException(404, "Unknown provider")
    if not prov.api_key_configured():
        return {"ok": False, "status": "unconfigured", "message": "API key not set on server"}
    ok, msg = prov.test_connection()
    with SyncSessionLocal() as session:
        row = session.execute(select(AiResearcher).where(AiResearcher.provider_slug == slug)).scalar_one_or_none()
        if row:
            row.connection_status = "connected" if ok else "error"
            row.last_connection_test_at = datetime.now(UTC)
            row.last_connection_error = None if ok else msg
            session.commit()
    return {"ok": ok, "status": "connected" if ok else "error", "message": msg}


@router.post("/researchers/{slug}/run-cycle")
async def manual_cycle(slug: str, _: User = Depends(get_current_user)) -> dict:
    try:
        ai_researcher_cycle_task.delay(slug)
        return {"ok": True, "queued": True, "provider_slug": slug}
    except Exception as exc:
        with SyncSessionLocal() as session:
            from app.services.ai_arena.cycle import run_researcher_cycle

            row = session.execute(select(AiResearcher).where(AiResearcher.provider_slug == slug)).scalar_one_or_none()
            if not row:
                raise HTTPException(404, "Researcher not found") from exc
            out = run_researcher_cycle(session, row, manual=True)
            session.commit()
            return {"ok": True, "queued": False, "result": out}