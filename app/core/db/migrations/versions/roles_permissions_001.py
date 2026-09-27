"""Staff roles with permission sets, and time-limited access

Revision ID: roles_permissions_001
Revises: process_settings_001
Create Date: 2026-09-25

Plan item 0.4. Adds the PRODUCTION, COMPLIANCE, SALES and AUDITOR values to the
``user_role`` enum (ADMIN and MEMBER keep their meaning: MEMBER is shown as "Staff" and
keeps today's access), ``users.access_expires_at`` so an Auditor's account stops working
on a set date, and invite-link columns so admins can add people without choosing their
password.

Downgrade maps the new roles back to MEMBER before rebuilding the two-value enum. That is
lossy (an Auditor becomes Staff) but is the only way back to the old type.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "roles_permissions_001"
down_revision: Union[str, None] = "process_settings_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'PRODUCTION'")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'COMPLIANCE'")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'SALES'")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'AUDITOR'")
    op.add_column("users", sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True))
    # Invite links: an admin adds a person and sends them a one-time link to set their own
    # password. Only a SHA-256 of the token is stored.
    op.add_column("users", sa.Column("invite_token_hash", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("invite_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_invite_token_hash", "users", ["invite_token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_invite_token_hash", table_name="users")
    op.drop_column("users", "invite_expires_at")
    op.drop_column("users", "invite_token_hash")
    op.drop_column("users", "access_expires_at")
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE text USING role::text")
    op.execute("UPDATE users SET role = 'MEMBER' WHERE role NOT IN ('ADMIN', 'MEMBER')")
    op.execute("DROP TYPE user_role")
    op.execute("CREATE TYPE user_role AS ENUM ('ADMIN', 'MEMBER')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role")
