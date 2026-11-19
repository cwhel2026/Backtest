"""Persist streaming market events for replay and recovery.

Revision ID: 010
Revises: 009
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_market_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("exchange_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_received_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_mode", sa.String(32), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_live_market_events_symbol_ts", "live_market_events", ["symbol", "exchange_ts"])


def downgrade() -> None:
    op.drop_index("ix_live_market_events_symbol_ts", table_name="live_market_events")
    op.drop_table("live_market_events")