"""PostgreSQL: trigger + GUC app.inventory_qty_guard blocks quantity writes without app allow (bulk SQL safe).

Revision ID: inv_qty_pg_guard_001
Revises: add_first_last_name_to_user_001

Non-PostgreSQL dialects: no-op (ORM-only guard remains).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "inv_qty_pg_guard_001"
down_revision: Union[str, None] = "add_first_last_name_to_user_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION inventory_items_enforce_qty_write_guard()
        RETURNS TRIGGER AS $$
        BEGIN
          IF coalesce(current_setting('app.migration_mode', true), '0') = '1' THEN
            RETURN NEW;
          END IF;
          IF coalesce(current_setting('app.inventory_qty_guard', true), '0') = '1' THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'INSERT' THEN
            RAISE EXCEPTION 'inventory_items: quantity INSERT blocked (set app.inventory_qty_guard via app, or app.migration_mode for migrations)';
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.quantity IS DISTINCT FROM NEW.quantity THEN
            RAISE EXCEPTION 'inventory_items: quantity UPDATE blocked (set app.inventory_qty_guard via app, or app.migration_mode for migrations)';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_inventory_items_qty_write_guard ON inventory_items;")
    op.execute(
        """
        CREATE TRIGGER trg_inventory_items_qty_write_guard
        BEFORE INSERT OR UPDATE OF quantity ON inventory_items
        FOR EACH ROW EXECUTE PROCEDURE inventory_items_enforce_qty_write_guard();
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_inventory_items_qty_write_guard ON inventory_items;")
    op.execute("DROP FUNCTION IF EXISTS inventory_items_enforce_qty_write_guard();")
