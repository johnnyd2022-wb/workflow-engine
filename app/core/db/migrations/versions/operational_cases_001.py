"""Operational cases (A1): operational_cases, operational_case_links, operational_case_events.

Revision ID: operational_cases_001
Revises: ee_synced_seq_idx_001

Additive only: three new tables, no change to existing data. Fully reversible on
disposable/internal data only -- the downgrade drops all case data, which is destructive
to any real case history (see .agents/specs/operational_cases.md rollout plan: "A schema
downgrade drops new tables and is destructive to new case data; use only on disposable
fixtures. Retained-data application rollback is specified below [separately, via the
read-only history routes and export CLI]."). Never run this downgrade against a database
holding real case data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "operational_cases_001"
down_revision: str | None = "ee_synced_seq_idx_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_STATUS_VALUES = ("open", "acknowledged", "in_progress", "resolved", "verified", "dismissed")
_ACTIVE_STATUS_VALUES = ("open", "acknowledged", "in_progress", "resolved")


def upgrade() -> None:
    op.create_table(
        "operational_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="critical"),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("check_id", sa.String(100), nullable=False),
        sa.Column("source_entity_type", sa.String(50), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_action", sa.String(2000), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "previous_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operational_cases.id"), nullable=True
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"status IN {_STATUS_VALUES}", name="ck_operational_cases_status"),
        sa.CheckConstraint("severity IN ('critical')", name="ck_operational_cases_severity"),
    )
    op.create_index("ix_operational_cases_org_id", "operational_cases", ["org_id"])
    op.create_index("ix_operational_cases_org_status_due", "operational_cases", ["org_id", "status", "due_at"])
    op.create_index(
        "ix_operational_cases_org_severity_updated",
        "operational_cases",
        ["org_id", "severity", sa.text("updated_at DESC"), sa.text("id DESC")],
    )
    # Last guard against a concurrent duplicate case for the same source identity: at
    # most one row with an "active" status per (org, source_type, check_id,
    # source_entity_type, source_entity_id).
    op.create_index(
        "uq_operational_cases_active_source",
        "operational_cases",
        ["org_id", "source_type", "check_id", "source_entity_type", "source_entity_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN {_ACTIVE_STATUS_VALUES}"),
    )

    op.create_table(
        "operational_case_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operational_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation", sa.String(20), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("relation IN ('source', 'evidence')", name="ck_operational_case_links_relation"),
    )
    op.create_index("ix_operational_case_links_org_id", "operational_case_links", ["org_id"])
    op.create_index("ix_operational_case_links_case", "operational_case_links", ["org_id", "case_id"])

    op.create_table(
        "operational_case_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operational_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("actor_label", sa.String(255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "entity_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entity_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "case_id", "case_version", name="uq_operational_case_events_case_version"),
    )
    op.create_index("ix_operational_case_events_org_id", "operational_case_events", ["org_id"])
    op.create_index(
        "ix_operational_case_events_case_version",
        "operational_case_events",
        ["org_id", "case_id", sa.text("case_version DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_operational_case_events_case_version", table_name="operational_case_events")
    op.drop_index("ix_operational_case_events_org_id", table_name="operational_case_events")
    op.drop_table("operational_case_events")

    op.drop_index("ix_operational_case_links_case", table_name="operational_case_links")
    op.drop_index("ix_operational_case_links_org_id", table_name="operational_case_links")
    op.drop_table("operational_case_links")

    op.drop_index("uq_operational_cases_active_source", table_name="operational_cases")
    op.drop_index("ix_operational_cases_org_severity_updated", table_name="operational_cases")
    op.drop_index("ix_operational_cases_org_status_due", table_name="operational_cases")
    op.drop_index("ix_operational_cases_org_id", table_name="operational_cases")
    op.drop_table("operational_cases")
