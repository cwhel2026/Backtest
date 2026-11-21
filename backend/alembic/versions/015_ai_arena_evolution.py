"""AI arena 5.2 — evolution limits, paper attribution, cycle recovery."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_researchers",
        sa.Column("max_refinement_depth", sa.Integer(), server_default="2", nullable=False),
    )
    op.add_column(
        "ai_researchers",
        sa.Column("max_child_experiments", sa.Integer(), server_default="3", nullable=False),
    )
    op.add_column(
        "ai_researchers",
        sa.Column("max_backtests_per_cycle", sa.Integer(), server_default="6", nullable=False),
    )
    op.add_column(
        "ai_research_cycles",
        sa.Column("worker_token", sa.String(64), nullable=True),
    )
    op.add_column(
        "ai_research_cycles",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "paper_slots",
        sa.Column("arena_attribution", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("paper_slots", "arena_attribution")
    op.drop_column("ai_research_cycles", "heartbeat_at")
    op.drop_column("ai_research_cycles", "worker_token")
    op.drop_column("ai_researchers", "max_backtests_per_cycle")
    op.drop_column("ai_researchers", "max_child_experiments")
    op.drop_column("ai_researchers", "max_refinement_depth")