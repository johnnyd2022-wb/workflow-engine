"""Persist immutable planning timing snapshots and editable proposed batches.

Revision ID: planned_batches_001
Revises: multiple_sites_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "planned_batches_001"
down_revision = "multiple_sites_001"
branch_labels = None
depends_on = None


def upgrade():
    for table, name in (
        ("processes", "uq_processes_planning_org_id"),
        ("planning_demands", "uq_planning_demands_org_id"),
        ("executions", "uq_executions_planning_org_id"),
    ):
        op.create_unique_constraint(name, table, ["org_id", "id"])
    op.create_table(
        "planning_workflow_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("process_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_output_id", UUID(as_uuid=True), nullable=False),
        sa.Column("batch_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("workflow_fingerprint", sa.String(64), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_planning_settings_org_id"),
        sa.UniqueConstraint("org_id", "process_id", "source_output_id", name="uq_planning_settings_output"),
        sa.ForeignKeyConstraint(
            ["org_id", "process_id"], ["processes.org_id", "processes.id"], name="fk_planning_settings_org_process"
        ),
        sa.CheckConstraint(
            "batch_quantity > 0 AND batch_quantity <= 99999999999999.9999", name="ck_planning_settings_quantity"
        ),
        sa.CheckConstraint("revision > 0", name="ck_planning_settings_revision"),
    )
    op.create_table(
        "planning_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("demand_id", UUID(as_uuid=True), nullable=False),
        sa.Column("process_id", UUID(as_uuid=True), nullable=False),
        sa.Column("setting_id", UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source_output_id", UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", UUID(as_uuid=True), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("batch_number", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(20), nullable=False, server_default="blocked"),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("proposed_start_date", sa.Date(), nullable=False),
        sa.Column("theoretical_ready_date", sa.Date(), nullable=True),
        sa.Column("forecast_ready_date", sa.Date(), nullable=True),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("blockers", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_planning_batches_org_id"),
        sa.UniqueConstraint("org_id", "demand_id", "generation", "batch_number", name="uq_planning_batch_generation"),
        sa.UniqueConstraint("execution_id", name="uq_planning_batch_execution"),
        sa.ForeignKeyConstraint(
            ["org_id", "demand_id"],
            ["planning_demands.org_id", "planning_demands.id"],
            name="fk_planning_batch_org_demand",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "process_id"], ["processes.org_id", "processes.id"], name="fk_planning_batch_org_process"
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "setting_id"],
            ["planning_workflow_settings.org_id", "planning_workflow_settings.id"],
            name="fk_planning_batch_org_setting",
        ),
        sa.ForeignKeyConstraint(["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_planning_batch_org_site"),
        sa.ForeignKeyConstraint(
            ["org_id", "execution_id"], ["executions.org_id", "executions.id"], name="fk_planning_batch_org_execution"
        ),
        sa.CheckConstraint("quantity > 0 AND quantity <= 99999999999999.9999", name="ck_planning_batch_quantity"),
        sa.CheckConstraint("priority >= 0 AND priority <= 100", name="ck_planning_batch_priority"),
        sa.CheckConstraint("revision > 0 AND generation > 0 AND batch_number > 0", name="ck_planning_batch_revision"),
        sa.CheckConstraint("status IN ('blocked','planned','cancelled','started')", name="ck_planning_batch_status"),
        sa.CheckConstraint(
            "theoretical_ready_date IS NULL OR theoretical_ready_date >= proposed_start_date",
            name="ck_planning_batch_dates",
        ),
        sa.CheckConstraint("status != 'started' OR execution_id IS NOT NULL", name="ck_planning_batch_started"),
    )
    for table, columns in (
        ("planning_workflow_settings", ("org_id", "process_id")),
        ("planning_batches", ("org_id", "demand_id", "process_id", "site_id", "proposed_start_date")),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.drop_table("planning_batches")
    op.drop_table("planning_workflow_settings")
    for table, name in (
        ("executions", "uq_executions_planning_org_id"),
        ("planning_demands", "uq_planning_demands_org_id"),
        ("processes", "uq_processes_planning_org_id"),
    ):
        op.drop_constraint(name, table, type_="unique")
