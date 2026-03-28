"""WASTAGE movements: optional FK to inventory_wastage for dedup (one ledger row per wastage record).

Revision ID: inv_mov_wastage_fk_001 (<=32 chars for alembic_version.version_num VARCHAR(32))
Revises: inventory_movements_001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "inv_mov_wastage_fk_001"
down_revision: Union[str, None] = "inventory_movements_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "inventory_movements" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("inventory_movements")}
    if "source_wastage_id" in cols:
        return
    op.add_column(
        "inventory_movements",
        sa.Column(
            "source_wastage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_wastage.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_inventory_movements_source_wastage",
        "inventory_movements",
        ["source_wastage_id"],
    )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "inventory_movements" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("inventory_movements")}
    if "source_wastage_id" not in cols:
        return
    op.drop_constraint("uq_inventory_movements_source_wastage", "inventory_movements", type_="unique")
    op.drop_column("inventory_movements", "source_wastage_id")
