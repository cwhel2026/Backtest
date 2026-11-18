"""Store last paper-desk scan so the UI can show it is working.

Revision ID: 006
Revises: 005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_accounts", sa.Column("last_scan", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("paper_accounts", "last_scan")
