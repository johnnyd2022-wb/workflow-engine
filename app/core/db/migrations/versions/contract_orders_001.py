"""Staff contract customers, orders, lines and batch associations (plan 7.2a).

Declarations of materials and duty do not change stock ownership or excise treatment.
Existing production remains unassociated; no historic customer assignments are guessed.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "contract_orders_001"
down_revision = "planner_demands_001"
branch_labels = None
depends_on = None


def _identity():
    return [
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
    ]


def _times(updated=True):
    rows = [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]
    if updated:
        rows.append(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    return rows


def upgrade():
    op.create_table(
        "contract_customers",
        *_identity(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "crm_contact_id", UUID(as_uuid=True), sa.ForeignKey("xero_contacts.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        *_times(),
        sa.UniqueConstraint("org_id", "id", name="uq_contract_customers_org_id"),
        sa.UniqueConstraint("org_id", "name", name="uq_contract_customers_org_name"),
    )
    op.create_table(
        "contract_orders",
        *_identity(),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("reference", sa.String(100), nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("duty_responsibility", sa.String(30), nullable=False),
        sa.Column("customer_cca_reference", sa.String(255), nullable=True),
        *_times(),
        sa.UniqueConstraint("org_id", "id", name="uq_contract_orders_org_id"),
        sa.UniqueConstraint("org_id", "reference", name="uq_contract_orders_org_reference"),
        sa.ForeignKeyConstraint(
            ["org_id", "customer_id"], ["contract_customers.org_id", "contract_customers.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("status IN ('draft','confirmed','completed','cancelled')", name="ck_contract_order_status"),
        sa.CheckConstraint(
            "duty_responsibility IN ('producer_licensee','customer_licensee','customer_underbond')",
            name="ck_contract_order_duty",
        ),
        sa.CheckConstraint(
            "duty_responsibility = 'producer_licensee' OR (customer_cca_reference IS NOT NULL AND length(trim(customer_cca_reference)) > 0)",
            name="ck_contract_order_customer_cca",
        ),
    )
    op.create_table(
        "contract_order_lines",
        *_identity(),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("materials_source", sa.String(20), nullable=False),
        sa.Column("spec_reference", sa.String(500), nullable=True),
        sa.Column("process_id", UUID(as_uuid=True), sa.ForeignKey("processes.id", ondelete="RESTRICT"), nullable=True),
        sa.Column(
            "process_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("process_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("source_output_id", UUID(as_uuid=True), nullable=True),
        *_times(),
        sa.UniqueConstraint("org_id", "order_id", "id", name="uq_contract_lines_org_order_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "order_id"], ["contract_orders.org_id", "contract_orders.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_contract_line_quantity"),
        sa.CheckConstraint("materials_source IN ('producer','customer','mixed')", name="ck_contract_line_materials"),
    )
    op.create_table(
        "contract_order_executions",
        *_identity(),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("line_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "execution_id", UUID(as_uuid=True), sa.ForeignKey("executions.id", ondelete="RESTRICT"), nullable=False
        ),
        *_times(False),
        sa.ForeignKeyConstraint(
            ["org_id", "order_id", "line_id"],
            ["contract_order_lines.org_id", "contract_order_lines.order_id", "contract_order_lines.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "execution_id", name="uq_contract_execution_assignment"),
    )
    for table, columns in {
        "contract_customers": ["org_id"],
        "contract_orders": ["org_id", "customer_id", "due_date"],
        "contract_order_lines": ["org_id", "order_id"],
        "contract_order_executions": ["org_id", "order_id", "line_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table in ("contract_order_executions", "contract_order_lines", "contract_orders", "contract_customers"):
        op.drop_table(table)
