"""GL-P01b: goods a customer sent back, kept apart from the money (credit note) and the duty.

One row per physical return. It may come from a Xero credit-note line, or be recorded on its
own (a swap, a breakage collected by a rep). What happened to the goods depends on condition:

* ``resaleable`` - back into stock: the batch it was sold from when known, else a new lot;
* ``damaged``    - back as a new lot placed on quality hold (GL-P02) until someone decides;
* ``destroyed``  - nothing came back into stock (the customer or carrier disposed of it).

A return that put stock back inside the licensed area is listed on the excise draft as a
possible credit to raise with Customs; it is never claimed automatically.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

import app.core.db.models.lot_hold  # noqa: F401 -- registers the hold FK target
import app.features.crm.models.xero_credit_note_line  # noqa: F401 -- registers the credit-line FK target
from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now

CONDITIONS = ("resaleable", "damaged", "destroyed")


class SalesReturn(TenantScoped, Base):
    __tablename__ = "sales_returns"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_sales_returns_org_id"),
        ForeignKeyConstraint(
            ["org_id", "credit_note_line_id"],
            ["xero_credit_note_lines.org_id", "xero_credit_note_lines.id"],
            name="fk_sales_return_org_credit_line",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "original_lot_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_sales_return_org_original_lot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "resulting_lot_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_sales_return_org_resulting_lot",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="ck_sales_return_quantity"),
        CheckConstraint("condition IN ('resaleable', 'damaged', 'destroyed')", name="ck_sales_return_condition"),
        CheckConstraint(
            "(condition = 'destroyed') = (resulting_lot_id IS NULL)", name="ck_sales_return_stock_matches_condition"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_note_line_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    allocation_id = Column(UUID(as_uuid=True), nullable=True)  # the FIFO sale line it reverses, when known
    xero_invoice_id = Column(String(100), nullable=True)
    product_name = Column(String(500), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    condition = Column(String(20), nullable=False)
    received_on = Column(Date, nullable=False)
    original_lot_id = Column(UUID(as_uuid=True), nullable=True)
    resulting_lot_id = Column(UUID(as_uuid=True), nullable=True)
    hold_id = Column(UUID(as_uuid=True), ForeignKey("lot_holds.id", ondelete="RESTRICT"), nullable=True)
    note = Column(Text, nullable=True)
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
