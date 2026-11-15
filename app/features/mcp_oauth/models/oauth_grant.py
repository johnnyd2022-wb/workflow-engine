"""A person's connection of one client to their account (what "Connected apps" lists), the codes
issued under it, and its tokens. All three are tenant tables with composite ``(org_id, ...)`` FKs."""

import uuid

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class OAuthGrant(TenantScoped, Base):
    __tablename__ = "oauth_grants"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_oauth_grants_org_id"),
        ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], name="fk_oauth_grants_user", ondelete="CASCADE"
        ),
        # M2: one live grant per person per client; reconnecting replaces its tokens.
        Index(
            "uq_oauth_grants_live",
            "org_id",
            "user_id",
            "client_pk",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    client_pk = Column(UUID(as_uuid=True), ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False)
    scope = Column(Text, nullable=False, default="bize.read", server_default="bize.read")
    resource = Column(Text, nullable=False)
    # The user's password fingerprint when they approved (auth_stamp). A different one now means the
    # password has changed since, which ends the grant (GL-A02 parity with sessions).
    auth_stamp = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    last_used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    revoked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    revoked_reason = Column(Text, nullable=True)


class OAuthAuthorizationCode(TenantScoped, Base):
    __tablename__ = "oauth_authorization_codes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "grant_id"],
            ["oauth_grants.org_id", "oauth_grants.id"],
            name="fk_oauth_codes_grant",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    code_hash = Column(Text, nullable=False, unique=True)
    code_challenge = Column(Text, nullable=False)
    redirect_uri = Column(Text, nullable=False)
    resource = Column(Text, nullable=False)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)


class OAuthToken(TenantScoped, Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_oauth_tokens_org_id"),
        CheckConstraint("kind IN ('access','refresh')", name="ck_oauth_tokens_kind"),
        ForeignKeyConstraint(
            ["org_id", "grant_id"],
            ["oauth_grants.org_id", "oauth_grants.id"],
            name="fk_oauth_tokens_grant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "replaced_by_id"],
            ["oauth_tokens.org_id", "oauth_tokens.id"],
            name="fk_oauth_tokens_replaced_by",
            ondelete="SET NULL (replaced_by_id)",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    kind = Column(Text, nullable=False)
    token_hash = Column(Text, nullable=False, unique=True)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    revoked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    replaced_by_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
