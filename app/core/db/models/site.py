"""Physical sites beneath an organisation (plan 7.1 foundations)."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class Site(TenantScoped, Base):
    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_sites_org_id"),
        Index("uq_sites_org_name", "org_id", text("lower(name)"), unique=True),
        Index("uq_sites_org_default", "org_id", unique=True, postgresql_where=text("is_default")),
        CheckConstraint("kind IN ('manufacturing','storage','retail','warehouse','event')", name="ck_sites_kind"),
        CheckConstraint("NOT is_default OR is_active", name="ck_sites_default_active"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(120), nullable=False)
    address = Column(String(500), nullable=True)
    kind = Column(String(30), nullable=False, default="manufacturing", server_default="manufacturing")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    is_default = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
