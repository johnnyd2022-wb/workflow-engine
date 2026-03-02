"""Add evidence_status to execution_evidence (PENDING -> ACTIVE after finalize)

Revision ID: add_evidence_status_001
Revises: add_execution_evidence_001
Create Date: 2025-02-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_evidence_status_001"
down_revision: Union[str, None] = "add_execution_evidence_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "execution_evidence",
        sa.Column("evidence_status", sa.String(32), nullable=False, server_default="active"),
    )
    op.create_index(op.f("ix_execution_evidence_evidence_status"), "execution_evidence", ["evidence_status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_execution_evidence_evidence_status"), table_name="execution_evidence")
    op.drop_column("execution_evidence", "evidence_status")
