"""The current final product image for a workflow."""

from uuid import uuid4

from sqlalchemy import Column, ForeignKeyConstraint, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped


class ProductImage(TenantScoped, Base):
    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint("process_id", name="uq_product_images_process_id"),
        ForeignKeyConstraint(
            ["org_id", "process_id"],
            ["processes.org_id", "processes.id"],
            name="fk_product_images_workflow",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    process_id = Column(UUID(as_uuid=True), nullable=False)
    content = Column(LargeBinary, nullable=False)
