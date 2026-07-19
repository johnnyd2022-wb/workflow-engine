"""Stores idempotent API responses (e.g. inventory wastage) for safe client retries."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class ApiIdempotencyKey(Base):
    """One row per (org, client key); payload hash must match for replay."""

    __tablename__ = "api_idempotency_keys"
    __table_args__ = (UniqueConstraint("org_id", "key", name="uq_api_idempotency_org_key"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    key = Column(String(128), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    response_json = Column(Text, nullable=False)
    http_status = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
