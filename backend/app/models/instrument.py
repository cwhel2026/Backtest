import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AssetClass


class Instrument(Base):
    """Extensible CME futures instrument registry with exchange metadata."""

    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(Enum(AssetClass, name="asset_class"), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), default="CME", nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    tick_size: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    tick_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    trading_hours: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Chicago", nullable=False)
    contract_months: Mapped[str] = mapped_column(String(64), default="HMUZ", nullable=False)
    roll_convention: Mapped[str] = mapped_column(String(64), default="volume", nullable=False)

    micro_of: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_micro: Mapped[bool] = mapped_column(default=False, nullable=False)

    default_commission_per_side: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("2.50"))
    default_clearing_fee: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.00"))

    metadata_extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class FuturesContract(Base):
    __tablename__ = "futures_contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    root_symbol: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    contract_month: Mapped[str] = mapped_column(String(8), nullable=False)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)