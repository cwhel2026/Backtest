"""Live Strategy Lab — forward tests, ledger, live candles, paper broker orders.

Revision ID: 009
Revises: 008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
  # enums created implicitly by sqlalchemy on first use — define explicitly for PG
    op.execute(
        "CREATE TYPE live_feed_connection_status AS ENUM "
        "('disconnected','connecting','connected','stale','degraded','error')"
    )
    op.execute(
        "CREATE TYPE market_latency_mode AS ENUM "
        "('realtime','delayed','historical_replay','synthetic')"
    )
    op.execute(
        "CREATE TYPE forward_test_state AS ENUM "
        "('historical_research','historically_validated','forward_test_pending',"
        "'forward_test_running','forward_test_paused','forward_test_failed',"
        "'forward_test_review','paper_broker_eligible')"
    )
    op.execute(
        "CREATE TYPE forward_test_latency_mode AS ENUM "
        "('realtime','delayed','historical_replay','synthetic')"
    )
    op.execute(
        "CREATE TYPE paper_order_state AS ENUM "
        "('created','submitted','acknowledged','partially_filled','filled',"
        "'cancelled','expired','rejected')"
    )

    op.create_table(
        "live_feed_status",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column(
            "connection_status",
            postgresql.ENUM(name="live_feed_connection_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "latency_mode",
            postgresql.ENUM(name="market_latency_mode", create_type=False),
            nullable=False,
        ),
        sa.Column("symbols", sa.String(128), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_exchange_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_server_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_seconds", sa.Integer(), nullable=False),
        sa.Column("is_paused", sa.Boolean(), nullable=False),
        sa.Column("incidents", postgresql.JSONB(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider"),
    )

    op.create_table(
        "live_completed_candles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(18, 8), nullable=False),
        sa.Column("high", sa.Numeric(18, 8), nullable=False),
        sa.Column("low", sa.Numeric(18, 8), nullable=False),
        sa.Column("close", sa.Numeric(18, 8), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("exchange_event_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("server_received_ts", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "timeframe", "ts", name="uq_live_candle"),
    )
    op.create_index("ix_live_completed_candles_symbol", "live_completed_candles", ["symbol"])

    op.create_table(
        "live_incomplete_candles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("bucket_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "timeframe", name="uq_live_incomplete"),
    )

    op.create_table(
        "forward_test_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column(
            "research_state",
            postgresql.ENUM(name="forward_test_state", create_type=False),
            nullable=False,
        ),
        sa.Column("experimental", sa.Boolean(), nullable=False),
        sa.Column("frozen_specification", postgresql.JSONB(), nullable=False),
        sa.Column("runner_kind", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column(
            "latency_mode",
            postgresql.ENUM(name="forward_test_latency_mode", create_type=False),
            nullable=False,
        ),
        sa.Column("starting_equity", sa.Numeric(18, 2), nullable=False),
        sa.Column("equity", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_pnl", sa.Numeric(18, 4), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("win_count", sa.Integer(), nullable=False),
        sa.Column("max_drawdown", sa.Numeric(18, 4), nullable=False),
        sa.Column("high_water", sa.Numeric(18, 2), nullable=False),
        sa.Column("runner_state", postgresql.JSONB(), nullable=False),
        sa.Column("last_signal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_data_exchange_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_decision_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("baseline_backtest_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy_definitions.id"]),
        sa.ForeignKeyConstraint(["strategy_version_id"], ["strategy_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forward_test_runs_strategy_id", "forward_test_runs", ["strategy_id"])

    op.create_table(
        "forward_test_ledger_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("exchange_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("server_received_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forward_test_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uq_fwd_ledger_idem"),
    )
    op.create_index("ix_forward_test_ledger_events_run_id", "forward_test_ledger_events", ["run_id"])
    op.create_index("ix_forward_test_ledger_events_event_type", "forward_test_ledger_events", ["event_type"])

    op.create_table(
        "paper_broker_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_order_id", sa.String(64), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="paper_order_state", create_type=False),
            nullable=False,
        ),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("filled_qty", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("stop_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("avg_fill_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("uncertainty_tags", postgresql.JSONB(), nullable=False),
        sa.Column("exchange_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("server_received_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forward_test_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_broker_orders_run_id", "paper_broker_orders", ["run_id"])


def downgrade() -> None:
    op.drop_table("paper_broker_orders")
    op.drop_table("forward_test_ledger_events")
    op.drop_table("forward_test_runs")
    op.drop_table("live_incomplete_candles")
    op.drop_index("ix_live_completed_candles_symbol", table_name="live_completed_candles")
    op.drop_table("live_completed_candles")
    op.drop_table("live_feed_status")
    op.execute("DROP TYPE paper_order_state")
    op.execute("DROP TYPE forward_test_latency_mode")
    op.execute("DROP TYPE forward_test_state")
    op.execute("DROP TYPE market_latency_mode")
    op.execute("DROP TYPE live_feed_connection_status")