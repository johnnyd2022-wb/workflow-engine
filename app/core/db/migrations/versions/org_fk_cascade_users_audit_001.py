"""Add ON DELETE CASCADE to users.org_id and audit_logs.org_id FKs.

Revision ID: org_fk_cascade_users_audit_001
Revises: crm_sales_trace_cfg_001
Create Date: 2026-05-15
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "org_fk_cascade_users_audit_001"
down_revision: str | None = "crm_sales_trace_cfg_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("users_org_id_fkey", "users", type_="foreignkey")
    op.create_foreign_key(
        "users_org_id_fkey",
        "users",
        "organisations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("audit_logs_org_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_org_id_fkey",
        "audit_logs",
        "organisations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("users_org_id_fkey", "users", type_="foreignkey")
    op.create_foreign_key(
        "users_org_id_fkey",
        "users",
        "organisations",
        ["org_id"],
        ["id"],
    )

    op.drop_constraint("audit_logs_org_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_org_id_fkey",
        "audit_logs",
        "organisations",
        ["org_id"],
        ["id"],
    )
