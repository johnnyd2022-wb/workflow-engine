"""Sales contacts created in Biz-E: no Xero id until sent, a per-contact Xero sync choice, and the last send's outcome."""

import sqlalchemy as sa
from alembic import op

revision = "crm_contacts_created_in_bize_001"
down_revision = "admin_org_notes_documents_001"
branch_labels = None
depends_on = None


def upgrade():
    # A constant server default is a catalogue-only change in Postgres 11+, so existing rows read
    # "xero" without a table rewrite.
    op.add_column("xero_contacts", sa.Column("source", sa.String(10), nullable=False, server_default="xero"))
    op.add_column("xero_contacts", sa.Column("sync_to_xero", sa.Boolean(), nullable=True))
    op.add_column("xero_contacts", sa.Column("xero_push_status", sa.String(20), nullable=True))
    op.add_column("xero_contacts", sa.Column("xero_push_error", sa.Text(), nullable=True))
    op.add_column("xero_contacts", sa.Column("xero_pushed_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.alter_column("xero_contacts", "xero_contact_id", existing_type=sa.String(100), nullable=True)
    op.alter_column("xero_contacts", "xero_tenant_id", existing_type=sa.String(100), nullable=True)
    # The NOT NULL still holds for every contact that came from Xero.
    op.create_check_constraint(
        "ck_xero_contacts_xero_id_unless_bize",
        "xero_contacts",
        "source = 'bize' OR xero_contact_id IS NOT NULL",
    )


def downgrade():
    conn = op.get_bind()
    local_only = conn.execute(
        sa.text("SELECT count(*) FROM xero_contacts WHERE xero_contact_id IS NULL OR xero_tenant_id IS NULL")
    ).scalar()
    if local_only:
        # Restoring NOT NULL would need these rows deleted or invented ids; neither is a downgrade's call.
        raise RuntimeError(
            f"{local_only} sales contact(s) were created in Biz-E and are not in Xero. Send them to Xero "
            "or remove them before downgrading crm_contacts_created_in_bize_001."
        )
    op.drop_constraint("ck_xero_contacts_xero_id_unless_bize", "xero_contacts", type_="check")
    op.alter_column("xero_contacts", "xero_tenant_id", existing_type=sa.String(100), nullable=False)
    op.alter_column("xero_contacts", "xero_contact_id", existing_type=sa.String(100), nullable=False)
    op.drop_column("xero_contacts", "xero_pushed_at")
    op.drop_column("xero_contacts", "xero_push_error")
    op.drop_column("xero_contacts", "xero_push_status")
    op.drop_column("xero_contacts", "sync_to_xero")
    op.drop_column("xero_contacts", "source")
