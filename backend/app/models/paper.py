import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaperAccount(Base):
    """Simulated prop evaluation. Not a broker or a real prop-firm account."""

    __tablename__ = "paper_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), default="Prop sim $100k", nullable=False)
    starting_equity: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    high_water: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    day_start_equity: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    daily_loss_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    trailing_drawdown: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    profit_target: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class PaperSlot(Base):
    """One strategy forward-tested on the paper account. At most one open trade."""

    __tablename__ = "paper_slots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("paper_accounts.id"), index=True)
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_definitions.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), default="5m", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    last_bar_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    open_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    open_stop: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    open_target: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    open_entry_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_bars_held: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_initial_risk: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arena_attribution: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class PaperFill(Base):
    __tablename__ = "paper_fills"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("paper_accounts.id"), index=True)
    slot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("paper_slots.id"), index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    exit_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    exit_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
