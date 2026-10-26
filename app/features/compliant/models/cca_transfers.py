"""Goods sold to another business's Customs-controlled area (GL-P08).

Customs' operational policy *Product movement excise unpaid - alcohol* (v2.0, para 15) asks the
sending licensee to keep a register of every excise-unpaid movement: the destination CCA's name
and address, the date it moved, the carrier and consignment note, the date it was received, and
what moved. Para 16 asks the destination for a written acknowledgement of receipt.

A destination is another business's CCA (a duty free shop, an export warehouse, a contract
customer's licensed area). Linking it to a customer makes every sale to that customer a transfer
rather than a removal for home consumption. A departure is the register row for one sale.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now

DESTINATION_KINDS = ("duty_free", "export_warehouse", "manufacturer", "storage", "other")


class CcaDestination(TenantScoped, Base):
    __tablename__ = "cca_destinations"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_cca_destination_org_id"),
        UniqueConstraint("org_id", "cca_code", name="uq_cca_destination_org_code"),
        CheckConstraint(
            "kind IN ('duty_free','export_warehouse','manufacturer','storage','other')", name="ck_cca_destination_kind"
        ),
        # One customer maps to one destination, so a sale is never ambiguous.
        Index(
            "uq_cca_destination_org_contact",
            "org_id",
            "contact_id",
            unique=True,
            postgresql_where=text("contact_id IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    cca_code = Column(String(100), nullable=False)
    address = Column(String(500), nullable=False)
    kind = Column(String(20), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("xero_contacts.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class CcaDeparture(TenantScoped, Base):
    __tablename__ = "cca_departures"
    __table_args__ = (
        UniqueConstraint("org_id", "xero_invoice_id", name="uq_cca_departure_org_invoice"),
        ForeignKeyConstraint(
            ["org_id", "destination_id"],
            ["cca_destinations.org_id", "cca_destinations.id"],
            name="fk_cca_departure_destination",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "received_on IS NULL OR receipt_reference IS NOT NULL", name="ck_cca_departure_receipt_evidence"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    destination_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    xero_invoice_id = Column(String(100), nullable=False)
    moved_at = Column(DateTime(timezone=True), nullable=False)
    carrier = Column(String(200), nullable=False)
    consignment_note = Column(String(200), nullable=True)
    received_on = Column(Date, nullable=True)
    receipt_reference = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    recorded_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
