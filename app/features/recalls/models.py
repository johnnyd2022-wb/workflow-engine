"""GL-P03: a recall is an operational case plus what it reaches.

The case (``operational_cases``, ``source_type = 'recall'``) carries the owner, due date, status
and the resolve/verify sign-off. These tables carry the recall itself:

* ``recalls``          - the lot it started from, why, how serious, drill or real, what was held;
* ``recall_contacts``  - each customer who received affected stock: how much, whether a notice
  went out (Biz-E only drafts it, never sends), whether they acknowledged, and how much came
  back or was disposed of by them.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

import app.core.db.models.inventory_item  # noqa: F401 -- FK target
import app.features.crm.models.xero_contact  # noqa: F401 -- FK target
import app.features.operational_cases.models.operational_case  # noqa: F401 -- FK target
from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now

RISKS = ("health", "quality", "regulatory")


class Recall(TenantScoped, Base):
    __tablename__ = "recalls"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_recalls_org_id"),
        UniqueConstraint("org_id", "case_id", name="uq_recalls_org_case"),
        ForeignKeyConstraint(
            ["org_id", "case_id"],
            ["operational_cases.org_id", "operational_cases.id"],
            name="fk_recall_org_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "root_lot_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_recall_org_lot",
            ondelete="RESTRICT",
        ),
        CheckConstraint("risk IN ('health', 'quality', 'regulatory')", name="ck_recall_risk"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_recall_reason"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), nullable=False)
    root_lot_id = Column(UUID(as_uuid=True), nullable=False)
    reason = Column(Text, nullable=False)
    risk = Column(String(20), nullable=False)
    is_drill = Column(Boolean, nullable=False, default=False)
    # Lots in scope (the lot and everything made from it) and the holds this recall placed.
    scope_lots = Column(JSONB, nullable=False, default=list)
    hold_ids = Column(JSONB, nullable=False, default=list)
    opened_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    opened_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class RecallContact(TenantScoped, Base):
    __tablename__ = "recall_contacts"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_recall_contacts_org_id"),
        ForeignKeyConstraint(
            ["org_id", "recall_id"],
            ["recalls.org_id", "recalls.id"],
            name="fk_recall_contact_org_recall",
            ondelete="CASCADE",
        ),
        # Postgres NUMERIC accepts NaN and sorts it above every number, so "> 0" alone lets it in.
        CheckConstraint(
            "quantity_supplied <> 'NaN'::numeric AND recovered_qty <> 'NaN'::numeric AND disposed_qty <> 'NaN'::numeric",
            name="ck_recall_contact_finite",
        ),
        CheckConstraint("quantity_supplied > 0", name="ck_recall_contact_supplied"),
        CheckConstraint(
            "recovered_qty >= 0 AND disposed_qty >= 0 AND recovered_qty + disposed_qty <= quantity_supplied",
            name="ck_recall_contact_accounted",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recall_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("xero_contacts.id", ondelete="SET NULL"), nullable=True)
    customer_name = Column(String(255), nullable=False)
    product_name = Column(String(500), nullable=False)
    unit = Column(String(50), nullable=False)
    quantity_supplied = Column(Numeric(18, 4), nullable=False)
    invoices = Column(JSONB, nullable=False, default=list)  # invoice numbers, for the notice
    notice_sent_at = Column(DateTime(timezone=True), nullable=True)
    notice_channel = Column(String(100), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(255), nullable=True)  # who at the customer
    ack_note = Column(Text, nullable=True)
    unreachable_note = Column(Text, nullable=True)
    recovered_qty = Column(Numeric(18, 4), nullable=False, default=0)
    disposed_qty = Column(Numeric(18, 4), nullable=False, default=0)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
