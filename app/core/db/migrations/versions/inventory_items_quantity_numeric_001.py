"""inventory_items.quantity: VARCHAR -> NUMERIC(18,4) for typed storage and SQL-safe aggregates

Revision ID: inventory_quantity_numeric_001
Revises: add_first_last_name_to_user_001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "inventory_quantity_numeric_001"
down_revision: Union[str, None] = "add_first_last_name_to_user_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name if conn else ""
    if dialect == "postgresql":
        op.execute(
            sa.text(
                """
                ALTER TABLE inventory_items
                ALTER COLUMN quantity TYPE NUMERIC(18,4)
                USING (
                    CASE
                        WHEN quantity IS NULL OR trim(quantity::text) = '' THEN 0::numeric
                        ELSE trim(quantity::text)::numeric
                    END
                );
                """
            )
        )
    else:
        raise NotImplementedError(
            "inventory_items.quantity NUMERIC migration is implemented for PostgreSQL only. "
            "Adjust for your dialect or run against Postgres."
        )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name if conn else ""
    if dialect == "postgresql":
        op.execute(
            sa.text(
                """
                ALTER TABLE inventory_items
                ALTER COLUMN quantity TYPE VARCHAR(50)
                USING (
                    CASE
                        WHEN quantity IS NULL THEN ''
                        ELSE trim(to_char(quantity, 'FM999999999999999990.9999'))
                    END
                );
                """
            )
        )
    else:
        raise NotImplementedError("Downgrade for inventory_items.quantity is PostgreSQL-only.")
