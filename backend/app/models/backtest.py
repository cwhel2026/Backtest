import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import pg_enum
from app.models.enums import PerformanceCategory


class OhlcvBar(Base):
    __tablename__ = "ohlcv_bars"
    __table_args__ = (UniqueConstraint("dataset_id", "ts", name="uq_ohlcv_dataset_ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("historical_datasets.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_versions.id"), index=True
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_definitions.id"))
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("historical_datasets.id"))
    performance_category: Mapped[PerformanceCategory] = mapped_column(
        pg_enum(PerformanceCategory, "performance_category"),
        default=PerformanceCategory.BACKTEST,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    reproducibility_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    assumptions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    equity_curve: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backtest_runs.id"), index=True
    )
    trade_number: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    exit_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    exit_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    commissions: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    slippage: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    mae: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    mfe: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)