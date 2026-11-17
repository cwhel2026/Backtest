"""backtest and ohlcv storage

Revision ID: 002
Revises: 001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    performance_category = postgresql.ENUM(
        "backtest",
        "out_of_sample",
        "walk_forward",
        "paper",
        "live",
        name="performance_category",
        create_type=True,
    )

    op.create_table(
        "ohlcv_bars",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(18, 8), nullable=False),
        sa.Column("high", sa.Numeric(18, 8), nullable=False),
        sa.Column("low", sa.Numeric(18, 8), nullable=False),
        sa.Column("close", sa.Numeric(18, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["dataset_id"], ["historical_datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "ts", name="uq_ohlcv_dataset_ts"),
    )
    op.create_index("ix_ohlcv_bars_dataset_id", "ohlcv_bars", ["dataset_id"])
    op.create_index("ix_ohlcv_bars_ts", "ohlcv_bars", ["ts"])

    op.create_table(
        "backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("performance_category", performance_category, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("engine_version", sa.String(16), nullable=False),
        sa.Column("reproducibility_id", sa.String(64), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.Column("equity_curve", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["historical_datasets.id"]),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy_definitions.id"]),
        sa.ForeignKeyConstraint(["strategy_version_id"], ["strategy_versions.id"]),
    )
    op.create_index("ix_backtest_runs_strategy_version_id", "backtest_runs", ["strategy_version_id"])
    op.create_index("ix_backtest_runs_reproducibility_id", "backtest_runs", ["reproducibility_id"])

    op.create_table(
        "backtest_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("backtest_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trade_number", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("signal_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("exit_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("stop_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("target_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("exit_reason", sa.String(64), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(18, 4), nullable=False),
        sa.Column("commissions", sa.Numeric(18, 4), nullable=False),
        sa.Column("slippage", sa.Numeric(18, 4), nullable=False),
        sa.Column("net_pnl", sa.Numeric(18, 4), nullable=False),
        sa.Column("mae", sa.Numeric(18, 4), nullable=True),
        sa.Column("mfe", sa.Numeric(18, 4), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
    )
    op.create_index("ix_backtest_trades_backtest_run_id", "backtest_trades", ["backtest_run_id"])


def downgrade() -> None:
    op.drop_table("backtest_trades")
    op.drop_table("backtest_runs")
    op.drop_table("ohlcv_bars")
    sa.Enum(name="performance_category").drop(op.get_bind(), checkfirst=True)