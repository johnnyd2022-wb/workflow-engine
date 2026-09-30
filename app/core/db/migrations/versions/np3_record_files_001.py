"""Files attached to NP3 check evidence (attestations and log entries)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "np3_record_files_001"
down_revision = "portal_reorders_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "compliance_record_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "record_id", UUID(as_uuid=True), sa.ForeignKey("compliance_records.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("storage_name", sa.String(80), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_compliance_record_files_org_record", "compliance_record_files", ["org_id", "record_id"])


def downgrade():
    op.drop_index("ix_compliance_record_files_org_record", table_name="compliance_record_files")
    op.drop_table("compliance_record_files")
