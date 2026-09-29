"""One cached `/api/core/system-findings` payload per org.

The check suite behind that endpoint runs a DAG traversal per expired-with-stock raw
material -- ~1.3s / hundreds of queries for a real org, on a route the /core page hits on
every load. This table holds the last computed result so the common path is a single
indexed row read. It is invalidated (``stale = true``) by EventWriter on any
inventory/execution/process mutation, and recomputed lazily, once, on the next request
(single-flight via a pg advisory lock in app/features/compliance_checks/system_findings_cache.py).
"""

import uuid

import sqlalchemy as sa
from sqlalchemy import Boolean, Column, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class SystemFindingsCache(TenantScoped, Base):
    __tablename__ = "system_findings_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # org_id comes from TenantScoped; one cache row per org.
    payload = Column(JSONB, nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    stale = Column(Boolean, nullable=False, server_default=sa.false())

    __table_args__ = (UniqueConstraint("org_id", name="uq_system_findings_cache_org"),)
