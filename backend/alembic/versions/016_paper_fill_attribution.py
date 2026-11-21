"""Paper fill lineage for arena forward trades."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_fills",
        sa.Column("arena_attribution", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "paper_fills",
        sa.Column("execution_detail", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("paper_fills", "execution_detail")
    op.drop_column("paper_fills", "arena_attribution")