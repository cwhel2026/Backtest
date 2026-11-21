"""AI arena 5.1 — lineage, validation tiers, global guardrails."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_experiments", sa.Column("lifecycle_phase", sa.String(32), server_default="hypothesis", nullable=False))
    op.add_column("ai_experiments", sa.Column("parent_experiment_id", UUID(as_uuid=True), nullable=True))
    op.add_column("ai_experiments", sa.Column("reasoning_summary", sa.Text(), server_default="", nullable=False))
    op.add_column("ai_experiments", sa.Column("validation_tier", sa.String(32), server_default="pending", nullable=False))
    op.add_column("ai_experiments", sa.Column("validation_report", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("ai_experiments", sa.Column("strategy_id", UUID(as_uuid=True), nullable=True))
    op.add_column("ai_experiments", sa.Column("strategy_version_id", UUID(as_uuid=True), nullable=True))
    op.add_column("ai_experiments", sa.Column("lineage", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.create_foreign_key(
        "fk_ai_experiments_parent",
        "ai_experiments",
        "ai_experiments",
        ["parent_experiment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "ai_arena_settings",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("emergency_stop", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("global_daily_budget_usd", sa.Numeric(10, 4), server_default="10", nullable=False),
        sa.Column("global_monthly_budget_usd", sa.Numeric(10, 4), server_default="100", nullable=False),
        sa.Column("auto_paper_promotion", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("INSERT INTO ai_arena_settings (id) VALUES (1) ON CONFLICT DO NOTHING")


def downgrade() -> None:
    op.drop_table("ai_arena_settings")
    op.drop_constraint("fk_ai_experiments_parent", "ai_experiments", type_="foreignkey")
    op.drop_column("ai_experiments", "lineage")
    op.drop_column("ai_experiments", "strategy_version_id")
    op.drop_column("ai_experiments", "strategy_id")
    op.drop_column("ai_experiments", "validation_report")
    op.drop_column("ai_experiments", "validation_tier")
    op.drop_column("ai_experiments", "reasoning_summary")
    op.drop_column("ai_experiments", "parent_experiment_id")
    op.drop_column("ai_experiments", "lifecycle_phase")