"""Paper slots: timeframe, open-trade management state, last error.

Revision ID: 005
Revises: 004
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_slots", sa.Column("timeframe", sa.String(8), nullable=False, server_default="5m"))
    op.add_column("paper_slots", sa.Column("open_bars_held", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("paper_slots", sa.Column("open_initial_risk", sa.Numeric(18, 8), nullable=True))
    op.add_column("paper_slots", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("paper_slots", sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("paper_slots", "last_refresh_at")
    op.drop_column("paper_slots", "last_error")
    op.drop_column("paper_slots", "open_initial_risk")
    op.drop_column("paper_slots", "open_bars_held")
    op.drop_column("paper_slots", "timeframe")
