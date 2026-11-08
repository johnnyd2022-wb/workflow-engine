"""Sales to another business's Customs-controlled area: destinations and the movement register (GL-P08)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "cca_transfers_001"
down_revision = "excise_category_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cca_destinations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("cca_code", sa.String(100), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), sa.ForeignKey("xero_contacts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_cca_destination_org_id"),
        sa.UniqueConstraint("org_id", "cca_code", name="uq_cca_destination_org_code"),
        sa.CheckConstraint(
            "kind IN ('duty_free','export_warehouse','manufacturer','storage','other')", name="ck_cca_destination_kind"
        ),
    )
    op.create_index("ix_cca_destinations_org_id", "cca_destinations", ["org_id"])
    op.create_index(
        "uq_cca_destination_org_contact",
        "cca_destinations",
        ["org_id", "contact_id"],
        unique=True,
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )
    op.create_table(
        "cca_departures",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("destination_id", UUID(as_uuid=True), nullable=False),
        sa.Column("xero_invoice_id", sa.String(100), nullable=False),
        sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("carrier", sa.String(200), nullable=False),
        sa.Column("consignment_note", sa.String(200)),
        sa.Column("received_on", sa.Date()),
        sa.Column("receipt_reference", sa.String(500)),
        sa.Column("notes", sa.Text()),
        sa.Column("recorded_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "xero_invoice_id", name="uq_cca_departure_org_invoice"),
        sa.ForeignKeyConstraint(
            ["org_id", "destination_id"],
            ["cca_destinations.org_id", "cca_destinations.id"],
            name="fk_cca_departure_destination",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "received_on IS NULL OR receipt_reference IS NOT NULL", name="ck_cca_departure_receipt_evidence"
        ),
    )
    op.create_index("ix_cca_departures_org_id", "cca_departures", ["org_id"])
    op.create_index("ix_cca_departures_destination_id", "cca_departures", ["destination_id"])


def downgrade():
    op.drop_table("cca_departures")
    op.drop_table("cca_destinations")
