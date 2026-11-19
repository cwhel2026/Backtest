"""Persist strategy decision events on backtest runs.

Revision ID: 008
Revises: 007
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_runs", sa.Column("simulation_log", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_runs", "simulation_log")