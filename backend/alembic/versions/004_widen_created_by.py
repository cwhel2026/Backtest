"""Widen strategy_hypotheses.created_by for long user emails.

Revision ID: 004
Revises: 003
"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "strategy_hypotheses",
        "created_by",
        existing_type=sa.String(32),
        type_=sa.String(128),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "strategy_hypotheses",
        "created_by",
        existing_type=sa.String(128),
        type_=sa.String(32),
        existing_nullable=False,
    )