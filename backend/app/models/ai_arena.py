"""AI Research Arena — one independent researcher per LLM provider."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text  # noqa: I001
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PROVIDER_SLUGS = (
    "openai",
    "anthropic",
    "google",
    "moonshot",
    "deepseek",
    "xai",
    "qwen",
    "mistral",
)


class AiResearcher(Base):
    __tablename__ = "ai_researchers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_slug: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    activated_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    research_frequency_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    daily_budget_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("2"), nullable=False)
    monthly_budget_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("25"), nullable=False)
    max_concurrent_experiments: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    connection_status: Mapped[str] = mapped_column(String(32), default="unconfigured", nullable=False)
    last_connection_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_connection_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    objectives: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_cycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_activity: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class AiArenaSettings(Base):
    __tablename__ = "ai_arena_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    global_daily_budget_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("10"), nullable=False)
    global_monthly_budget_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("100"), nullable=False)
    auto_paper_promotion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class AiExperiment(Base):
    __tablename__ = "ai_experiments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    researcher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_researchers.id"), nullable=False)
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    parent_experiment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_experiments.id"), nullable=True)
    lifecycle_phase: Mapped[str] = mapped_column(String(32), default="hypothesis", nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reasoning_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    validation_tier: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    validation_report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lineage: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    specification: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    spec_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    strategy_family: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), default="MNQ", nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), default="5m", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="proposed", nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    backtest_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    validation_metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    improved_from_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    author_provider_slug: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiResearchCycle(Base):
    __tablename__ = "ai_research_cycles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    researcher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_researchers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    phase: Mapped[str] = mapped_column(String(64), default="init", nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiApiUsage(Base):
    __tablename__ = "ai_api_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    researcher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_researchers.id"), nullable=False)
    provider_slug: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    call_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class AiStrategyCritique(Base):
    __tablename__ = "ai_strategy_critiques"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_experiments.id"), nullable=False)
    critic_provider_slug: Mapped[str] = mapped_column(String(32), nullable=False)
    author_provider_slug: Mapped[str] = mapped_column(String(32), nullable=False)
    critique: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )