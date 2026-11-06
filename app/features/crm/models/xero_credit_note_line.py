"""A product and return-decision record for one Xero credit-note line."""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKeyConstraint, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

import app.core.db.models.user  # noqa: F401 -- registers the tenant-scoped actor FK
import app.features.crm.models.product_mapping  # noqa: F401 -- registers the composite mapping FK
import app.features.crm.models.xero_credit_note  # noqa: F401 -- registers the parent FK target
from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class XeroCreditNoteLine(TenantScoped, Base):
    __tablename__ = "xero_credit_note_lines"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_xero_credit_note_lines_org_id"),
        UniqueConstraint("org_id", "credit_note_id", "line_key", name="uq_xero_credit_note_line_key"),
        ForeignKeyConstraint(
            ["org_id", "credit_note_id"],
            ["xero_credit_notes.org_id", "xero_credit_notes.id"],
            name="fk_xero_credit_note_line_org_note",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "product_mapping_id"],
            ["product_mappings.org_id", "product_mappings.id"],
            name="fk_xero_credit_note_line_org_mapping",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "no_return_by_user_id"],
            ["users.org_id", "users.id"],
            name="fk_xero_credit_note_line_org_actor",
            ondelete="RESTRICT",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_note_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    line_key = Column(String(160), nullable=False)
    item_code = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    quantity = Column(Numeric(18, 4), nullable=True)
    unit_amount = Column(Numeric(18, 4), nullable=True)
    line_amount = Column(Numeric(18, 4), nullable=True)
    product_mapping_id = Column(UUID(as_uuid=True), nullable=True)
    is_current = Column(Boolean, nullable=False, default=True, server_default="true")
    no_return_note = Column(Text, nullable=True)
    no_return_by_user_id = Column(UUID(as_uuid=True), nullable=True)
    no_return_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
