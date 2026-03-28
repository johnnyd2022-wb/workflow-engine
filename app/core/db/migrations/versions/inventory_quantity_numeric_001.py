"""inventory_items.quantity to NUMERIC(18,4) (was string storage).

Revision ID: inventory_quantity_numeric_001
Revises: add_first_last_name_to_user_001

This revision id must stay stable: existing databases record it in alembic_version.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "inventory_quantity_numeric_001"
down_revision: Union[str, None] = "add_first_last_name_to_user_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pg_guard_function_exists(conn) -> bool:
    if conn.dialect.name != "postgresql":
        return False
    row = conn.execute(
        sa.text(
            """
            SELECT 1 FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public' AND p.proname = 'inventory_items_enforce_qty_write_guard'
            LIMIT 1
            """
        )
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "inventory_items" not in insp.get_table_names():
        return
    cols = {c["name"]: c for c in insp.get_columns("inventory_items")}
    qty = cols.get("quantity")
    if qty is None:
        return
    tname = str(qty["type"]).upper()
    if "NUMERIC" in tname or "DECIMAL" in tname:
        return
    had_pg_guard = _pg_guard_function_exists(conn)
    if conn.dialect.name == "postgresql":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_inventory_items_qty_write_guard ON inventory_items;"))
    op.execute(
        sa.text(
            """
            ALTER TABLE inventory_items
            ALTER COLUMN quantity TYPE NUMERIC(18, 4)
            USING (
                CASE
                    WHEN trim(both from quantity::text) = '' THEN 0::numeric
                    ELSE trim(both from quantity::text)::numeric
                END
            );
            """
        )
    )
    if conn.dialect.name == "postgresql" and had_pg_guard:
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_inventory_items_qty_write_guard
                BEFORE INSERT OR UPDATE OF quantity ON inventory_items
                FOR EACH ROW EXECUTE PROCEDURE inventory_items_enforce_qty_write_guard();
                """
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "inventory_items" not in insp.get_table_names():
        return
    had_pg_guard = _pg_guard_function_exists(conn)
    if conn.dialect.name == "postgresql":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_inventory_items_qty_write_guard ON inventory_items;"))
    op.execute(
        sa.text(
            """
            ALTER TABLE inventory_items
            ALTER COLUMN quantity TYPE VARCHAR(50)
            USING trim(to_char(quantity, 'FM9999999999999999.9999'));
            """
        )
    )
    if conn.dialect.name == "postgresql" and had_pg_guard:
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_inventory_items_qty_write_guard
                BEFORE INSERT OR UPDATE OF quantity ON inventory_items
                FOR EACH ROW EXECUTE PROCEDURE inventory_items_enforce_qty_write_guard();
                """
            )
        )
