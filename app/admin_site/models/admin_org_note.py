"""A support note biz-e staff keep about an organisation."""

import uuid

from sqlalchemy import Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models import organisation  # noqa: F401 -- the table org_id points at
from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class AdminOrgNote(TenantScoped, Base):
    __tablename__ = "admin_org_notes"
    __table_args__ = (Index("ix_admin_org_notes_org_created", "org_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    body = Column(Text, nullable=False)
    # Staff are not users of any organisation, so the author is their sign-in email.
    author_email = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
