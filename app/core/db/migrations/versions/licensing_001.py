"""Liquor licensing: licences, manager's certificates, incident and refusal log

Revision ID: licensing_001
Revises: verifications_001
Create Date: 2026-09-28

Plan item 2.5. A register of alcohol licences (including special licences for events)
and managers' certificates with the dates that must not lapse, and the incident and
refusal log an inspector asks to see.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "licensing_001"
down_revision: Union[str, None] = "verifications_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _org():
    return sa.Column(
        "org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )


def _user(name: str):
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def upgrade() -> None:
    op.create_table(
        "liquor_licences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org(),
        sa.Column("kind", sa.String(10), nullable=False),  # on | off | club | special
        sa.Column("licence_number", sa.String(100), nullable=True),
        sa.Column("issuing_dlc", sa.String(255), nullable=True),
        sa.Column("premises", sa.String(500), nullable=True),
        sa.Column("endorsements", JSONB, nullable=False, server_default="[]"),  # e.g. ["s40_remote_sales"]
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("sale_hours", sa.String(255), nullable=True),
        sa.Column("delivery_hours_start", sa.Time(), nullable=True),
        sa.Column("delivery_hours_end", sa.Time(), nullable=True),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("annual_fee_due_on", sa.Date(), nullable=True),
        sa.Column("renewal_lodged_on", sa.Date(), nullable=True),
        # special licences (events)
        sa.Column("event_name", sa.String(255), nullable=True),
        sa.Column("event_starts_on", sa.Date(), nullable=True),
        sa.Column("event_ends_on", sa.Date(), nullable=True),
        sa.Column("manager_on_duty", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="current"),  # current | ended
        _user("created_by_user_id"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_liquor_licences_org", "liquor_licences", ["org_id", "status"])
    op.create_table(
        "manager_certificates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org(),
        _user("user_id"),
        sa.Column("holder_name", sa.String(255), nullable=False),
        sa.Column("certificate_number", sa.String(100), nullable=False),
        sa.Column("issuing_dlc", sa.String(255), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("renewal_lodged_on", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_manager_certificates_org", "manager_certificates", ["org_id", "active"])
    op.create_table(
        "licensing_log_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org(),
        # id_refusal | intoxication_refusal | incident | controlled_purchase
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),  # cellar door, online order, event
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("action_taken", sa.Text(), nullable=True),
        sa.Column("staff_name", sa.String(255), nullable=True),
        sa.Column("reference", sa.String(255), nullable=True),  # order number, police reference
        _user("created_by_user_id"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_licensing_log_org_time", "licensing_log_entries", ["org_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_licensing_log_org_time", table_name="licensing_log_entries")
    op.drop_table("licensing_log_entries")
    op.drop_index("ix_manager_certificates_org", table_name="manager_certificates")
    op.drop_table("manager_certificates")
    op.drop_index("ix_liquor_licences_org", table_name="liquor_licences")
    op.drop_table("liquor_licences")
