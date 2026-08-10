"""Tighten org_id to NOT NULL on steps, execution_steps, trusted_devices,
two_factor_backup_codes, now that tenant_org_id_backfill_001 has populated every row.

Revision ID: tenant_org_id_notnull_001
Revises: tenant_org_id_backfill_001
Create Date: 2026-08-09

Final revision of the three-part sequence (add nullable + FK + index -> backfill -> tighten
to NOT NULL) per migration-safety's nullable-first rule, so the NOT NULL constraint never has
to be applied in the same statement as an ALTER TABLE ADD COLUMN. TenantScoped's org_id
column (app/core/db/models/tenant_mixin.py) is declared nullable=False, so these four models
only fully match that mixin once this revision has run.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "tenant_org_id_notnull_001"
down_revision: str | None = "tenant_org_id_backfill_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("steps", "execution_steps", "trusted_devices", "two_factor_backup_codes")


def upgrade() -> None:
    for table in TABLES:
        op.alter_column(table, "org_id", nullable=False)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.alter_column(table, "org_id", nullable=True)
