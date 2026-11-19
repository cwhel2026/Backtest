"""Live Strategy Lab — forward tests, ledger, candles, paper broker orders."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import pg_enum
from app.models.enums import ForwardTestState, LiveFeedConnectionStatus, MarketLatencyMode, PaperOrderState


class LiveFeedStatus(Base):
    __tablename__ = "live_feed_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    connection_status: Mapped[LiveFeedConnectionStatus] = mapped_column(
        pg_enum(LiveFeedConnectionStatus, "live_feed_connection_status"),
        default=LiveFeedConnectionStatus.DISCONNECTED,
        nullable=False,
    )
    latency_mode: Mapped[MarketLatencyMode] = mapped_column(
        pg_enum(MarketLatencyMode, "market_latency_mode"),
        default=MarketLatencyMode.SYNTHETIC,
        nullable=False,
    )
    symbols: Mapped[str] = mapped_column(String(128), default="MNQ,MES,MGC", nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_exchange_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_server_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stale_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    is_paused: Mapped[bool] = mapped_column(default=True, nullable=False)
    incidents: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class LiveCompletedCandle(Base):
    __tablename__ = "live_completed_candles"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "ts", name="uq_live_candle"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="replay", nullable=False)
    exchange_event_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_received_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LiveIncompleteCandle(Base):
    __tablename__ = "live_incomplete_candles"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", name="uq_live_incomplete"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    bucket_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class ForwardTestRun(Base):
    __tablename__ = "forward_test_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_definitions.id"), index=True)
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), default="5m", nullable=False)
    research_state: Mapped[ForwardTestState] = mapped_column(
        pg_enum(ForwardTestState, "forward_test_state"),
        default=ForwardTestState.FORWARD_TEST_PENDING,
        nullable=False,
    )
    experimental: Mapped[bool] = mapped_column(default=False, nullable=False)
    frozen_specification: Mapped[dict] = mapped_column(JSONB, nullable=False)
    runner_kind: Mapped[str] = mapped_column(String(32), default="dsl_bar_close", nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="replay", nullable=False)
    latency_mode: Mapped[MarketLatencyMode] = mapped_column(
        pg_enum(MarketLatencyMode, "forward_test_latency_mode"),
        default=MarketLatencyMode.HISTORICAL_REPLAY,
        nullable=False,
    )
    starting_equity: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("100000"), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("100000"), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    high_water: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("100000"), nullable=False)
    runner_state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_data_exchange_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_decision_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_backtest_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class ForwardTestLedgerEvent(Base):
    __tablename__ = "forward_test_ledger_events"
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key", name="uq_fwd_ledger_idem"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forward_test_runs.id"), index=True, nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    exchange_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_received_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PaperBrokerOrder(Base):
    __tablename__ = "paper_broker_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("forward_test_runs.id"), index=True)
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[PaperOrderState] = mapped_column(
        pg_enum(PaperOrderState, "paper_order_state"),
        default=PaperOrderState.CREATED,
        nullable=False,
    )
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    uncertainty_tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    exchange_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_received_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )