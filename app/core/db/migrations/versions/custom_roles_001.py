"""Custom roles: an org's own permission sets, cloned from a built-in role

Revision ID: custom_roles_001
Revises: licensing_001
Create Date: 2026-09-28

Plan item 0.4c. A custom role keeps the built-in role it was cloned from (``base_role``),
which a user assigned to it also carries in ``users.role``, and the permissions ticked for
it. Deleting a role that people still hold is refused.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "custom_roles_001"
down_revision: Union[str, None] = "licensing_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("base_role", sa.String(20), nullable=False),
        sa.Column("permissions", JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "name", name="uq_org_roles_org_name"),
    )
    op.create_index("ix_org_roles_org_id", "org_roles", ["org_id"])
    op.add_column(
        "users",
        sa.Column(
            "custom_role_id", UUID(as_uuid=True), sa.ForeignKey("org_roles.id", ondelete="RESTRICT"), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "custom_role_id")
    op.drop_index("ix_org_roles_org_id", table_name="org_roles")
    op.drop_table("org_roles")
