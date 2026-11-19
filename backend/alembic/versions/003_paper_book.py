"""prop paper book — forward test with simulated fills

Revision ID: 003
Revises: 002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("starting_equity", sa.Numeric(18, 2), nullable=False),
        sa.Column("equity", sa.Numeric(18, 2), nullable=False),
        sa.Column("high_water", sa.Numeric(18, 2), nullable=False),
        sa.Column("day_start_equity", sa.Numeric(18, 2), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("daily_loss_limit", sa.Numeric(18, 2), nullable=False),
        sa.Column("trailing_drawdown", sa.Numeric(18, 2), nullable=False),
        sa.Column("profit_target", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_bar_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_direction", sa.String(8), nullable=True),
        sa.Column("open_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("open_entry_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("open_stop", sa.Numeric(18, 8), nullable=True),
        sa.Column("open_target", sa.Numeric(18, 8), nullable=True),
        sa.Column("open_entry_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["paper_accounts.id"]),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy_definitions.id"]),
    )
    op.create_index("ix_paper_slots_account_id", "paper_slots", ["account_id"])
    op.create_index("ix_paper_slots_strategy_id", "paper_slots", ["strategy_id"])
    op.create_table(
        "paper_fills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_name", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("exit_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("exit_reason", sa.String(64), nullable=False),
        sa.Column("net_pnl", sa.Numeric(18, 4), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["paper_accounts.id"]),
        sa.ForeignKeyConstraint(["slot_id"], ["paper_slots.id"]),
    )
    op.create_index("ix_paper_fills_account_id", "paper_fills", ["account_id"])
    op.create_index("ix_paper_fills_slot_id", "paper_fills", ["slot_id"])


def downgrade() -> None:
    op.drop_table("paper_fills")
    op.drop_table("paper_slots")
    op.drop_table("paper_accounts")
