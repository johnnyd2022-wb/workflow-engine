"""Store one final product image per workflow."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "product_images_001"
down_revision = "xero_pending_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "product_images",
        sa.Column("process_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id", "process_id"],
            ["processes.org_id", "processes.id"],
            name="fk_product_images_workflow",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_product_images_org_id", "product_images", ["org_id"])


def downgrade():
    op.drop_table("product_images")
