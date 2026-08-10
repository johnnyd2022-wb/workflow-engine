"""Add nullable org_id + FK + index to steps, execution_steps, trusted_devices,
two_factor_backup_codes (schema only -- no data edits here, see migration-safety skill).

Revision ID: tenant_org_id_add_001
Revises: crm_revenue_baseline_target_001
Create Date: 2026-08-09

These four tables previously had no org_id column of their own -- tenancy was transitive
through a join to their parent (steps/execution_steps -> processes/executions; trusted_
devices/two_factor_backup_codes -> users). That transitive-only tenancy is exactly where
confirmed CRITICAL/MEDIUM cross-tenant reads happened (see .agents/reports/{inventory,
execution}/security-audit.md): a query fetched or joined these tables by ID without also
joining back to the parent's org_id, in the same files where a sibling method got it right.

Denormalizing org_id here lets these tables join the global ORM tenant filter (app/core/db/
tenant_filter.py, app/core/db/models/tenant_mixin.py) as plain TenantScoped models -- one
uniform equality filter for every tenant-scoped table, instead of a correlated-subquery
special case. (A subquery-based loader-criteria alternative was prototyped and rejected: it
also hit a SQLAlchemy lambda-caching restriction on Session/Query closure variables --
tests/test_tenant_filter_spike.py.)

Three-revision sequence per migration-safety: this one adds the column nullable (no lock-
risk default, no table scan), org_id is backfilled in tenant_org_id_backfill_001, and only
tenant_org_id_notnull_001 tightens it to NOT NULL once the backfill is confirmed complete.
The FK and index are added here already (both are safe on a nullable column) so the two
later revisions are pure data/constraint changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "tenant_org_id_add_001"
down_revision: str | None = "crm_revenue_baseline_target_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("steps", "execution_steps", "trusted_devices", "two_factor_backup_codes")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            f"{table}_org_id_fkey",
            table,
            "organisations",
            ["org_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_constraint(f"{table}_org_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "org_id")
