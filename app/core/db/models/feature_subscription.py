"""Per-org product entitlements.

A generic ``(org_id, feature_key)`` grant table: an org "has" a product area when it
holds an ``active`` row for that feature key. Deliberately distinct from any feature's
own "is this module configured / turned on" flag (e.g. ``ComplianceProfile.enabled``):
this table answers "is the tenant *entitled* to the product", which an un-configured but
paying org must still answer yes to.

Plain ``Base`` (not ``TenantScoped``) — the read path always filters ``org_id``
explicitly and inline (see ``FeatureSubscriptionRepository``), matching the sibling
``compliance_profiles`` / ``system_findings_cache`` pattern, and the admin CLI grants
across arbitrary orgs with no tenant context.
"""

import uuid

import sqlalchemy as sa
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class FeatureSubscription(Base):
    __tablename__ = "feature_subscriptions"
    __table_args__ = (
        UniqueConstraint("org_id", "feature_key", name="uq_feature_subscriptions_org_feature"),
        Index("ix_feature_subscriptions_org_feature", "org_id", "feature_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    feature_key = Column(String(80), nullable=False)
    active = Column(Boolean, nullable=False, server_default=sa.true(), default=True)
    granted_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    granted_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(String(500), nullable=True)

    def __repr__(self) -> str:
        state = "active" if self.active else "inactive"
        return f"<FeatureSubscription(org_id={self.org_id}, feature_key={self.feature_key!r}, {state})>"
