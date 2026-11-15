"""Public MCP 8.2b: OAuth clients, grants, codes, tokens and the per-org MCP switch.

Revision ID: mcp_oauth_001
Revises: costing_overheads_001

Six new tables and nothing else (spec .agents/specs/public-mcp.md, "Data model"):

* ``oauth_clients`` is the one deliberately global table (a client like "Claude" serves every
  organisation and holds no tenant data).
* ``mcp_org_settings`` / ``mcp_allowed_roles`` are the org's switch (off by default) and the roles
  allowed to connect an assistant.
* ``oauth_grants`` / ``oauth_authorization_codes`` / ``oauth_tokens`` carry ``org_id`` with
  composite ``(org_id, ...)`` foreign keys, as everywhere else. Codes and tokens are stored as
  SHA-256 hashes only.

Reversible. Downgrade drops the six tables; it refuses while ``mcp_org_settings`` or
``mcp_allowed_roles`` hold rows, because an administrator typed those and nothing else keeps a
copy. Clients, grants, codes and tokens are credentials that a person re-issues by connecting
again, so they are dropped.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "mcp_oauth_001"
down_revision = "costing_overheads_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "oauth_clients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=False),
        sa.Column("redirect_uris", ARRAY(sa.Text()), nullable=False),
        sa.Column("registration", sa.Text(), nullable=False),
        sa.Column("metadata_url", sa.Text(), nullable=True),
        sa.Column("metadata_fetched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("disabled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("client_id", name="uq_oauth_clients_client_id"),
        sa.CheckConstraint(
            "registration IN ('dcr','metadata_url','first_party')", name="ck_oauth_clients_registration"
        ),
    )

    op.create_table(
        "mcp_org_settings",
        sa.Column(
            "org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "updated_by_user_id"],
            ["users.org_id", "users.id"],
            name="fk_mcp_org_settings_updated_by",
            ondelete="SET NULL (updated_by_user_id)",
        ),
    )

    op.create_table(
        "mcp_allowed_roles",
        sa.Column(
            "org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("role_key", sa.Text(), primary_key=True),
        sa.CheckConstraint(
            "role_key ~ '^(builtin:[a-z_]+|custom:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$'",
            name="ck_mcp_allowed_roles_key",
        ),
    )

    op.create_table(
        "oauth_grants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "client_pk", UUID(as_uuid=True), sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("scope", sa.Text(), nullable=False, server_default="bize.read"),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("auth_stamp", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("org_id", "id", name="uq_oauth_grants_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], name="fk_oauth_grants_user", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_oauth_grants_org_id", "oauth_grants", ["org_id"])
    op.create_index(
        "uq_oauth_grants_live",
        "oauth_grants",
        ["org_id", "user_id", "client_pk"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code_hash", name="uq_oauth_codes_code_hash"),
        sa.ForeignKeyConstraint(
            ["org_id", "grant_id"],
            ["oauth_grants.org_id", "oauth_grants.id"],
            name="fk_oauth_codes_grant",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_oauth_authorization_codes_org_id", "oauth_authorization_codes", ["org_id"])
    op.create_index("ix_oauth_authorization_codes_grant_id", "oauth_authorization_codes", ["grant_id"])

    op.create_table(
        "oauth_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("replaced_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_oauth_tokens_token_hash"),
        sa.UniqueConstraint("org_id", "id", name="uq_oauth_tokens_org_id"),
        sa.CheckConstraint("kind IN ('access','refresh')", name="ck_oauth_tokens_kind"),
        sa.ForeignKeyConstraint(
            ["org_id", "grant_id"],
            ["oauth_grants.org_id", "oauth_grants.id"],
            name="fk_oauth_tokens_grant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "replaced_by_id"],
            ["oauth_tokens.org_id", "oauth_tokens.id"],
            name="fk_oauth_tokens_replaced_by",
            ondelete="SET NULL (replaced_by_id)",
        ),
    )
    op.create_index("ix_oauth_tokens_org_id", "oauth_tokens", ["org_id"])
    op.create_index("ix_oauth_tokens_grant_id", "oauth_tokens", ["grant_id"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(text("SELECT 1 FROM mcp_org_settings LIMIT 1")).first():
        raise RuntimeError("mcp_org_settings contains rows an administrator set; downgrading would lose them")
    if bind.execute(text("SELECT 1 FROM mcp_allowed_roles LIMIT 1")).first():
        raise RuntimeError("mcp_allowed_roles contains rows an administrator set; downgrading would lose them")
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_grants")
    op.drop_table("mcp_allowed_roles")
    op.drop_table("mcp_org_settings")
    op.drop_table("oauth_clients")
