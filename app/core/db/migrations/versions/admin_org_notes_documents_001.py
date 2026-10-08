"""Admin site: internal notes and documents kept about an organisation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "admin_org_notes_documents_001"
down_revision = "np3_record_files_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_org_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_email", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_org_notes_org_id", "admin_org_notes", ["org_id"])
    op.create_index("ix_admin_org_notes_org_created", "admin_org_notes", ["org_id", "created_at"])
    op.create_table(
        "admin_org_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_org_documents_org_id", "admin_org_documents", ["org_id"])
    op.create_index("ix_admin_org_documents_org_created", "admin_org_documents", ["org_id", "created_at"])


def downgrade():
    op.drop_table("admin_org_documents")
    op.drop_table("admin_org_notes")
