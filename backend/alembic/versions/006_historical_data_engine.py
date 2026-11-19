"""Historical data engine 3.0 — checksum + budget ledger.

Revision ID: 006
Revises: 005
"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("historical_datasets", sa.Column("content_checksum", sa.String(64), nullable=True))
    op.create_table(
        "research_data_budget_months",
        sa.Column("month_key", sa.String(7), primary_key=True),
        sa.Column("budget_gbp", sa.Numeric(12, 2), nullable=False, server_default="50"),
        sa.Column("estimated_usd", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("approved_usd", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("actual_usd", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("research_data_budget_months")
    op.drop_column("historical_datasets", "content_checksum")