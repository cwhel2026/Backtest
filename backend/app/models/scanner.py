"""Persisted market scanner setups and worker health beats."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScannerSetup(Base):
    __tablename__ = "scanner_setups"
    __table_args__ = (
        UniqueConstraint("setup_id", name="uq_scanner_setup_id"),
        Index("ix_scanner_setups_symbol_status", "symbol", "status"),
        Index("ix_scanner_setups_detected_at", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    setup_id: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    contract: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    market_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    risk_reward: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feed_latency_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    forward_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    diagnostics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScannerWatchState(Base):
    """Incremental FSM state for symbol-wide detection (no paper run required)."""

    __tablename__ = "scanner_watch_states"
    __table_args__ = (UniqueConstraint("symbol", "strategy_key", name="uq_scanner_watch"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False)
    runner_state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_bar_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkerHealthBeat(Base):
    __tablename__ = "worker_health_beats"

    worker_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stale_after_seconds: Mapped[int] = mapped_column(default=600, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)