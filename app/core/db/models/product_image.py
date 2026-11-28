"""The current final product image for a workflow."""

from sqlalchemy import Column, ForeignKeyConstraint, LargeBinary
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped


class ProductImage(TenantScoped, Base):
    __tablename__ = "product_images"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "process_id"],
            ["processes.org_id", "processes.id"],
            name="fk_product_images_workflow",
            ondelete="CASCADE",
        ),
    )

    process_id = Column(UUID(as_uuid=True), primary_key=True)
    content = Column(LargeBinary, nullable=False)
