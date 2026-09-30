"""Contract orders declare commercial intent; stock and excise remain separate."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now

ORDER_STATUSES = ("draft", "confirmed", "completed", "cancelled")
MATERIALS_SOURCES = ("producer", "customer", "mixed")
DUTY_RESPONSIBILITIES = ("producer_licensee", "customer_licensee", "customer_underbond")


class ContractCustomer(TenantScoped, Base):
    __tablename__ = "contract_customers"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_contract_customers_org_id"),
        UniqueConstraint("org_id", "name", name="uq_contract_customers_org_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    crm_contact_id = Column(UUID(as_uuid=True), ForeignKey("xero_contacts.id", ondelete="RESTRICT"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ContractOrder(TenantScoped, Base):
    __tablename__ = "contract_orders"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_contract_orders_org_id"),
        UniqueConstraint("org_id", "id", "customer_id", name="uq_contract_order_customer_scope"),
        UniqueConstraint("org_id", "reference", name="uq_contract_orders_org_reference"),
        ForeignKeyConstraint(
            ["org_id", "customer_id"], ["contract_customers.org_id", "contract_customers.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("status IN ('draft','confirmed','completed','cancelled')", name="ck_contract_order_status"),
        CheckConstraint(
            "duty_responsibility IN ('producer_licensee','customer_licensee','customer_underbond')",
            name="ck_contract_order_duty",
        ),
        CheckConstraint(
            "duty_responsibility = 'producer_licensee' OR "
            "(customer_cca_reference IS NOT NULL AND length(trim(customer_cca_reference)) > 0)",
            name="ck_contract_order_customer_cca",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    reference = Column(String(100), nullable=False)
    due_date = Column(Date, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="draft", server_default="draft")
    duty_responsibility = Column(String(30), nullable=False)
    customer_cca_reference = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    customer = relationship("ContractCustomer")
    lines = relationship("ContractOrderLine", cascade="all, delete-orphan", order_by="ContractOrderLine.created_at")


class ContractOrderLine(TenantScoped, Base):
    __tablename__ = "contract_order_lines"
    __table_args__ = (
        UniqueConstraint("org_id", "order_id", "id", name="uq_contract_lines_org_order_id"),
        ForeignKeyConstraint(
            ["org_id", "order_id"], ["contract_orders.org_id", "contract_orders.id"], ondelete="CASCADE"
        ),
        CheckConstraint("quantity > 0", name="ck_contract_line_quantity"),
        CheckConstraint("materials_source IN ('producer','customer','mixed')", name="ck_contract_line_materials"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    product_name = Column(String(255), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    materials_source = Column(String(20), nullable=False)
    spec_reference = Column(String(500), nullable=True)
    process_id = Column(UUID(as_uuid=True), ForeignKey("processes.id", ondelete="RESTRICT"), nullable=True)
    process_version_id = Column(
        UUID(as_uuid=True), ForeignKey("process_versions.id", ondelete="RESTRICT"), nullable=True
    )
    source_output_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    batches = relationship(
        "ContractOrderExecution", cascade="all, delete-orphan", order_by="ContractOrderExecution.created_at"
    )


class ContractOrderExecution(TenantScoped, Base):
    __tablename__ = "contract_order_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "order_id", "line_id"],
            ["contract_order_lines.org_id", "contract_order_lines.order_id", "contract_order_lines.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("org_id", "execution_id", name="uq_contract_execution_assignment"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    line_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    execution = relationship("Execution")
