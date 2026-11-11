"""Purchase rules (roadmap 8.1c-2, spec .agents/specs/live-cogs.md "8.1c-2 build contract").

`purchase_rules` (normalised matchers, treatment, pre-fill template), `purchase_lines.
treatment_rule_id`, `costing_settings.last_history_from/to`. Additive. Downgrade refuses while
any rule exists (people's mappings, with no other copy).

Revision ID: costing_rules_001
Revises: costing_allocations_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "costing_rules_001"
down_revision = "costing_allocations_001"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade():
    op.create_table(
        "purchase_rules",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("account_code", sa.String(50), nullable=True),
        sa.Column("payee_pattern", sa.String(255), nullable=True),
        sa.Column("description_pattern", sa.String(500), nullable=True),
        sa.Column("match_type", sa.String(10), nullable=False, server_default="exact"),
        sa.Column("treatment", sa.String(20), nullable=False),
        sa.Column("template", postgresql.JSONB(), nullable=True),
        sa.Column("auto_record", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_purchase_rules_org_id"),
        sa.CheckConstraint(
            "account_code IS NOT NULL OR payee_pattern IS NOT NULL OR description_pattern IS NOT NULL",
            name="ck_purchase_rules_matcher",
        ),
        sa.CheckConstraint("match_type IN ('exact','contains')", name="ck_purchase_rules_match_type"),
        sa.CheckConstraint(
            "treatment IN ('stock','not_stock','duty','overhead')", name="ck_purchase_rules_treatment"
        ),
        sa.CheckConstraint("template IS NULL OR treatment = 'stock'", name="ck_purchase_rules_template_stock"),
    )
    op.create_index("ix_purchase_rules_org_id", "purchase_rules", ["org_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_purchase_rules_matchers ON purchase_rules (org_id, coalesce(account_code, ''), "
        "coalesce(payee_pattern, ''), coalesce(description_pattern, ''), match_type)"
    )
    op.add_column("purchase_lines", sa.Column("treatment_rule_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_purchase_lines_rule",
        "purchase_lines",
        "purchase_rules",
        ["org_id", "treatment_rule_id"],
        ["org_id", "id"],
        ondelete="SET NULL (treatment_rule_id)",
    )
    op.add_column("costing_settings", sa.Column("last_history_from", sa.Date(), nullable=True))
    op.add_column("costing_settings", sa.Column("last_history_to", sa.Date(), nullable=True))


def downgrade():
    if op.get_bind().execute(text("SELECT 1 FROM purchase_rules LIMIT 1")).first():
        raise RuntimeError("purchase_rules contains rows; downgrading would lose them")
    op.drop_column("costing_settings", "last_history_to")
    op.drop_column("costing_settings", "last_history_from")
    op.drop_constraint("fk_purchase_lines_rule", "purchase_lines", type_="foreignkey")
    op.drop_column("purchase_lines", "treatment_rule_id")
    op.execute("DROP INDEX IF EXISTS uq_purchase_rules_matchers")
    op.drop_index("ix_purchase_rules_org_id", table_name="purchase_rules")
    op.drop_table("purchase_rules")
