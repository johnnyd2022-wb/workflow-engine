"""Store site resource groups and per-step rough capacity assignments."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "planner_capacity_001"
down_revision = "planner_material_forecasts_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planning_capacity_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "site_id", name="uq_planning_capacity_org_site"),
        sa.ForeignKeyConstraint(["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_planning_capacity_site"),
        sa.CheckConstraint("revision > 0", name="ck_planning_capacity_revision"),
    )


def downgrade():
    op.drop_table("planning_capacity_settings")
