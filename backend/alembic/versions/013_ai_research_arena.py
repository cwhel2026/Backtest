"""AI research arena — independent researchers per provider."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_researchers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_slug", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("activated_by_user", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("model_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("research_frequency_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("daily_budget_usd", sa.Numeric(10, 4), nullable=False, server_default="2"),
        sa.Column("monthly_budget_usd", sa.Numeric(10, 4), nullable=False, server_default="25"),
        sa.Column("max_concurrent_experiments", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("connection_status", sa.String(32), nullable=False, server_default="unconfigured"),
        sa.Column("last_connection_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_connection_error", sa.Text(), nullable=True),
        sa.Column("memory", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("objectives", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("stats", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_cycle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_activity", sa.String(256), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "ai_experiments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("researcher_id", UUID(as_uuid=True), sa.ForeignKey("ai_researchers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cycle_id", UUID(as_uuid=True), nullable=True),
        sa.Column("hypothesis", sa.Text(), nullable=False, server_default=""),
        sa.Column("specification", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("spec_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("strategy_family", sa.String(64), nullable=False, server_default=""),
        sa.Column("symbol", sa.String(16), nullable=False, server_default="MNQ"),
        sa.Column("timeframe", sa.String(16), nullable=False, server_default="5m"),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("backtest_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("validation_metrics", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("improved_from_id", UUID(as_uuid=True), nullable=True),
        sa.Column("author_provider_slug", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ai_experiments_fingerprint", "ai_experiments", ["spec_fingerprint"])
    op.create_index("ix_ai_experiments_researcher", "ai_experiments", ["researcher_id", "created_at"])
    op.create_table(
        "ai_research_cycles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("researcher_id", UUID(as_uuid=True), sa.ForeignKey("ai_researchers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("phase", sa.String(64), nullable=False, server_default="init"),
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "ai_api_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("researcher_id", UUID(as_uuid=True), sa.ForeignKey("ai_researchers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_slug", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("call_kind", sa.String(64), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "ai_strategy_critiques",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("ai_experiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("critic_provider_slug", sa.String(32), nullable=False),
        sa.Column("author_provider_slug", sa.String(32), nullable=False),
        sa.Column("critique", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("ai_strategy_critiques")
    op.drop_table("ai_api_usage")
    op.drop_table("ai_research_cycles")
    op.drop_index("ix_ai_experiments_researcher", table_name="ai_experiments")
    op.drop_index("ix_ai_experiments_fingerprint", table_name="ai_experiments")
    op.drop_table("ai_experiments")
    op.drop_table("ai_researchers")