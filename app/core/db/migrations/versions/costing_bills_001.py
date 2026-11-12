"""Bills and supplier credits as purchase sources (roadmap 8.1f-1, spec .agents/specs/live-cogs.md
"8.1f-1 build contract"): widen ``ck_purchase_documents_source``.

Revision ID: costing_bills_001
Revises: costing_rules_001
"""

from alembic import op
from sqlalchemy import text

revision = "costing_bills_001"
down_revision = "costing_rules_001"
branch_labels = None
depends_on = None

NAME = "ck_purchase_documents_source"


def upgrade():
    op.drop_constraint(NAME, "purchase_documents", type_="check")
    op.create_check_constraint(NAME, "purchase_documents", "source IN ('xero_bank','xero_bill','xero_bill_credit')")


def downgrade():
    bind = op.get_bind()
    if bind.execute(text("SELECT 1 FROM purchase_documents WHERE source <> 'xero_bank' LIMIT 1")).first():
        raise RuntimeError("Bills or supplier credits are stored; downgrading would drop them from the constraint")
    op.drop_constraint(NAME, "purchase_documents", type_="check")
    op.create_check_constraint(NAME, "purchase_documents", "source IN ('xero_bank')")
