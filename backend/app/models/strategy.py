import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import StrategyLifecycle


class StrategyHypothesis(Base):
    __tablename__ = "strategy_hypotheses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    economic_rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(32), default="system", nullable=False)


class StrategyDefinition(Base):
    __tablename__ = "strategy_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hypothesis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_hypotheses.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(String(16), default="1m", nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[StrategyLifecycle] = mapped_column(
        Enum(StrategyLifecycle, name="strategy_lifecycle"),
        default=StrategyLifecycle.RESEARCHING,
        nullable=False,
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class StrategyVersion(Base):
    """Immutable strategy specification version."""

    __tablename__ = "strategy_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_definitions.id"))
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    specification: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0.0", nullable=False)
    changelog: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )