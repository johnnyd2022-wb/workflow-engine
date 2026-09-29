"""Pack size on sales product mappings

Revision ID: product_mapping_pack_size_001
Revises: roles_permissions_001
Create Date: 2026-09-25

Plan item 1.2: a Xero line such as "Wildflower 700ml - Case of 6" with quantity 2 is
12 bottles. ``units_per_line`` says how many stock units one line quantity takes;
existing mappings keep 1, so nothing changes until someone sets a pack size.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "product_mapping_pack_size_001"
down_revision: Union[str, None] = "roles_permissions_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_mappings",
        sa.Column("units_per_line", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint("ck_product_mappings_units_per_line_positive", "product_mappings", "units_per_line >= 1")


def downgrade() -> None:
    op.drop_constraint("ck_product_mappings_units_per_line_positive", "product_mappings", type_="check")
    op.drop_column("product_mappings", "units_per_line")
