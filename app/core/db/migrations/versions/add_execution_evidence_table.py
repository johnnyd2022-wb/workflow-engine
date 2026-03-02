"""Add execution_evidence table for evidence uploads

Revision ID: add_execution_evidence_001
Revises: uq_inventory_org_barcode_001
Create Date: 2025-02-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "add_execution_evidence_001"
down_revision: Union[str, None] = "uq_inventory_org_barcode_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'execution_evidence'
        )
    """))
    if result.scalar():
        return
    op.create_table(
        "execution_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("extra_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_execution_evidence_org_id"), "execution_evidence", ["org_id"], unique=False)
    op.create_index(op.f("ix_execution_evidence_execution_id"), "execution_evidence", ["execution_id"], unique=False)
    op.create_index(op.f("ix_execution_evidence_step_id"), "execution_evidence", ["step_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_execution_evidence_step_id"), table_name="execution_evidence")
    op.drop_index(op.f("ix_execution_evidence_execution_id"), table_name="execution_evidence")
    op.drop_index(op.f("ix_execution_evidence_org_id"), table_name="execution_evidence")
    op.drop_table("execution_evidence")
