"""Food-safety verifications and their corrective actions

Revision ID: verifications_001
Revises: stocktake_001
Create Date: 2026-09-28

Plan item 2.2. Each verification visit is recorded with its outcome and the frequency
step the verifier set (Food Regulations 94), so the next verification date is always
known; corrective actions carry owners and due dates.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "verifications_001"
down_revision: Union[str, None] = "stocktake_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_verifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("programme", sa.String(10), nullable=False),  # np1 | np2 | np3
        sa.Column("verified_on", sa.Date(), nullable=False),
        sa.Column("verifier_name", sa.String(255), nullable=False),
        sa.Column("verifier_agency", sa.String(255), nullable=True),
        sa.Column("report_reference", sa.String(255), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),  # acceptable | unacceptable
        sa.Column("initial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attitude", sa.String(20), nullable=True),  # willing | unwilling | immediate_risk
        sa.Column("step", sa.Integer(), nullable=False),  # 1-8, Food Regulations 94(1)
        sa.Column("next_due", sa.Date(), nullable=True),  # None at step 8 (no further verification)
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_compliance_verifications_org_date", "compliance_verifications", ["org_id", "verified_on"])
    op.create_table(
        "compliance_verification_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "verification_id",
            UUID(as_uuid=True),
            sa.ForeignKey("compliance_verifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("owner_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_name", sa.String(255), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),  # open | done
        sa.Column("done_on", sa.Date(), nullable=True),
        sa.Column("done_note", sa.String(500), nullable=True),
        sa.Column("done_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_compliance_verification_actions_org_status", "compliance_verification_actions", ["org_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_verification_actions_org_status", table_name="compliance_verification_actions")
    op.drop_table("compliance_verification_actions")
    op.drop_index("ix_compliance_verifications_org_date", table_name="compliance_verifications")
    op.drop_table("compliance_verifications")
