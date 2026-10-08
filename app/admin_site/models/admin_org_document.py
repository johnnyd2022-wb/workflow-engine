"""A file biz-e staff keep about an organisation, e.g. a signed contract. The bytes live
on the admin site's own volume (app/admin_site/documents.py); this row describes them."""

import uuid

from sqlalchemy import BigInteger, Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models import organisation  # noqa: F401 -- the table org_id points at
from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class AdminOrgDocument(TenantScoped, Base):
    __tablename__ = "admin_org_documents"
    __table_args__ = (Index("ix_admin_org_documents_org_created", "org_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    stored_name = Column(String(64), nullable=False)  # <uuid>.<ext>, never taken from the upload
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    uploaded_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
