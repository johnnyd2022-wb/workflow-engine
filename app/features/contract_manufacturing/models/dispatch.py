"""Contract goods leaving the CCA (GL-P08 part 2).

Every departure is either a transfer to another CCA or a removal entered for duty. A dispatch
for an order the customer is liable for is a transfer to the customer's CCA (Customs'
general authorisation covers a contract manufacturer sending finished goods to an owner who
holds a CCA licence); one the producer is liable for is a removal. The treatment is fixed when
the goods leave, with the destination it was sent to.
"""

import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, ForeignKeyConstraint, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now

TREATMENTS = ("cca_transfer", "removal")


class ContractDispatch(TenantScoped, Base):
    __tablename__ = "contract_dispatches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "order_id"],
            ["contract_orders.org_id", "contract_orders.id"],
            name="fk_contract_dispatch_order",
            ondelete="RESTRICT",
        ),
        CheckConstraint("treatment IN ('cca_transfer','removal')", name="ck_contract_dispatch_treatment"),
        CheckConstraint(
            "treatment = 'removal' OR (destination_cca IS NOT NULL AND length(trim(destination_cca)) > 0)",
            name="ck_contract_dispatch_destination",
        ),
        CheckConstraint(
            "received_on IS NULL OR (treatment = 'cca_transfer' AND receipt_reference IS NOT NULL)",
            name="ck_contract_dispatch_receipt",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    treatment = Column(String(20), nullable=False)
    destination_name = Column(String(255), nullable=False)
    destination_cca = Column(String(255), nullable=True)
    moved_at = Column(DateTime(timezone=True), nullable=False)
    carrier = Column(String(200), nullable=False)
    consignment_note = Column(String(200), nullable=True)
    received_on = Column(Date, nullable=True)
    receipt_reference = Column(String(500), nullable=True)
    recorded_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    lines = relationship(
        "ContractDispatchLine",
        primaryjoin="and_(ContractDispatch.id == foreign(ContractDispatchLine.dispatch_id), "
        "ContractDispatch.org_id == ContractDispatchLine.org_id)",
        viewonly=True,
        lazy="selectin",
    )


class ContractDispatchLine(TenantScoped, Base):
    __tablename__ = "contract_dispatch_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_contract_dispatch_line_item",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="ck_contract_dispatch_line_quantity"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispatch_id = Column(
        UUID(as_uuid=True), ForeignKey("contract_dispatches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    product_name = Column(String(255), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
