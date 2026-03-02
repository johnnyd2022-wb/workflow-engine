"""Add process_step_documents table for SOP (file + inline)

Revision ID: add_process_step_docs_001
Revises: add_evidence_status_001
Create Date: 2025-03-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "add_process_step_docs_001"
down_revision: Union[str, None] = "add_evidence_status_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'process_step_documents'
        )
    """
        )
    )
    if result.scalar():
        return

    op.create_table(
        "process_step_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("process_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=True),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["process_id"], ["processes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_process_step_documents_org_id"), "process_step_documents", ["org_id"], unique=False
    )
    op.create_index(
        op.f("ix_process_step_documents_process_id"), "process_step_documents", ["process_id"], unique=False
    )
    op.create_index(
        op.f("ix_process_step_documents_step_id"), "process_step_documents", ["step_id"], unique=False
    )
    # Either storage_path OR content_markdown must be set (soft delete keeps row, so we allow both null only when deleted_at is set)
    op.execute(
        """
        ALTER TABLE process_step_documents ADD CONSTRAINT chk_process_step_doc_content
        CHECK (
            (deleted_at IS NOT NULL) OR
            (storage_path IS NOT NULL AND storage_path != '') OR
            (content_markdown IS NOT NULL AND content_markdown != '')
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint("chk_process_step_doc_content", "process_step_documents", type_="check")
    op.drop_index(op.f("ix_process_step_documents_step_id"), table_name="process_step_documents")
    op.drop_index(op.f("ix_process_step_documents_process_id"), table_name="process_step_documents")
    op.drop_index(op.f("ix_process_step_documents_org_id"), table_name="process_step_documents")
    op.drop_table("process_step_documents")
