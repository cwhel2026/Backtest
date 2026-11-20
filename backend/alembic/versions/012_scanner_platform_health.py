"""Scanner setups and worker health beats.

Revision ID: 012
Revises: 011
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scanner_setups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("setup_id", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("contract", sa.String(32), nullable=True),
        sa.Column("strategy_key", sa.String(64), nullable=False),
        sa.Column("strategy_name", sa.String(128), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("stop_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("target_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("risk_reward", sa.Numeric(12, 4), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("data_source", sa.String(64), nullable=True),
        sa.Column("feed_latency_mode", sa.String(32), nullable=True),
        sa.Column("forward_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setup_id", name="uq_scanner_setup_id"),
    )
    op.create_index("ix_scanner_setups_symbol_status", "scanner_setups", ["symbol", "status"])
    op.create_index("ix_scanner_setups_detected_at", "scanner_setups", ["detected_at"])
    op.create_index("ix_scanner_setups_forward_run_id", "scanner_setups", ["forward_run_id"])

    op.create_table(
        "scanner_watch_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("strategy_key", sa.String(64), nullable=False),
        sa.Column("runner_state", postgresql.JSONB(), nullable=False),
        sa.Column("last_bar_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "strategy_key", name="uq_scanner_watch"),
    )

    op.create_table(
        "worker_health_beats",
        sa.Column("worker_name", sa.String(64), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale_after_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("worker_name"),
    )


def downgrade() -> None:
    op.drop_table("worker_health_beats")
    op.drop_table("scanner_watch_states")
    op.drop_index("ix_scanner_setups_forward_run_id", table_name="scanner_setups")
    op.drop_index("ix_scanner_setups_detected_at", table_name="scanner_setups")
    op.drop_index("ix_scanner_setups_symbol_status", table_name="scanner_setups")
    op.drop_table("scanner_setups")