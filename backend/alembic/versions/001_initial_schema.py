"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    asset_class = postgresql.ENUM(
        "equity_index", "metal", "energy", "currency", name="asset_class", create_type=True
    )
    data_provider_status = postgresql.ENUM(
        "not_configured", "configured", "connected", "error", name="data_provider_status", create_type=True
    )
    dataset_validation_status = postgresql.ENUM(
        "pending", "validated", "failed", name="dataset_validation_status", create_type=True
    )
    strategy_lifecycle = postgresql.ENUM(
        "researching",
        "backtesting",
        "rejected",
        "historically_validated",
        "paper_trading",
        "paper_validated",
        "eligible_for_approval",
        "approved_for_deployment",
        "paused",
        "retired",
        name="strategy_lifecycle",
        create_type=True,
    )
    research_job_kind = postgresql.ENUM(
        "data_ingestion",
        "backtest",
        "validation",
        "ai_hypothesis",
        "paper_sync",
        "health_check",
        name="research_job_kind",
        create_type=True,
    )
    research_job_status = postgresql.ENUM(
        "queued", "running", "completed", "failed", "cancelled", name="research_job_status", create_type=True
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "instruments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("asset_class", asset_class, nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False, server_default="CME"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("tick_size", sa.Numeric(18, 8), nullable=False),
        sa.Column("tick_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("multiplier", sa.Numeric(18, 4), nullable=False),
        sa.Column("trading_hours", postgresql.JSONB(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("contract_months", sa.String(64), nullable=False),
        sa.Column("roll_convention", sa.String(64), nullable=False),
        sa.Column("micro_of", sa.String(16), nullable=True),
        sa.Column("is_micro", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("default_commission_per_side", sa.Numeric(10, 4), nullable=False),
        sa.Column("default_clearing_fee", sa.Numeric(10, 4), nullable=False),
        sa.Column("metadata_extra", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"])

    op.create_table(
        "futures_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_symbol", sa.String(16), nullable=False),
        sa.Column("contract_month", sa.String(8), nullable=False),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_symbol", sa.String(64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "data_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("status", data_provider_status, nullable=False),
        sa.Column("config_hint", sa.Text(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
    )

    op.create_table(
        "historical_datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("data_providers.id")),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("instruments.id")),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_uri", sa.String(512), nullable=True),
        sa.Column("version_tag", sa.String(64), nullable=False),
        sa.Column("validation_status", dataset_validation_status, nullable=False),
        sa.Column("quality_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
    )

    op.create_table(
        "data_quality_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("historical_datasets.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duplicate_bars", sa.Integer(), nullable=False),
        sa.Column("missing_bars", sa.Integer(), nullable=False),
        sa.Column("gap_seconds_max", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )

    op.create_table(
        "strategy_hypotheses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("economic_rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=False),
    )

    op.create_table(
        "strategy_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("hypothesis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategy_hypotheses.id")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("instruments.id")),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("lifecycle", strategy_lifecycle, nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "strategy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategy_definitions.id")),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("specification", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "research_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", research_job_kind, nullable=False),
        sa.Column("status", research_job_status, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "research_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_jobs.id")),
        sa.Column("headline", sa.String(512), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("research_activities")
    op.drop_table("research_jobs")
    op.drop_table("strategy_versions")
    op.drop_table("strategy_definitions")
    op.drop_table("strategy_hypotheses")
    op.drop_table("data_quality_reports")
    op.drop_table("historical_datasets")
    op.drop_table("data_providers")
    op.drop_table("futures_contracts")
    op.drop_table("instruments")
    op.drop_table("users")
    sa.Enum(name="research_job_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="research_job_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="strategy_lifecycle").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="dataset_validation_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="data_provider_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="asset_class").drop(op.get_bind(), checkfirst=True)