"""Refine inventory_items quantity trigger: single unauthorized path (INSERT vs quantity-changing UPDATE).

Revision ID: inv_qty_pg_guard_002
Revises: inv_qty_pg_guard_001

Replaces function body only. INSERT and UPDATE are allowed when app.migration_mode=1 or
app.inventory_qty_guard=1; unauthorized UPDATEs that do not change quantity pass through.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "inv_qty_pg_guard_002"
down_revision: Union[str, None] = "inv_qty_pg_guard_001"
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
        DECLARE
          migration_ok boolean;
          guard_ok boolean;
        BEGIN
          migration_ok := coalesce(current_setting('app.migration_mode', true), '0') = '1';
          guard_ok := coalesce(current_setting('app.inventory_qty_guard', true), '0') = '1';
          IF migration_ok OR guard_ok THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.quantity IS NOT DISTINCT FROM NEW.quantity THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'inventory_items: quantity INSERT or quantity-changing UPDATE blocked (set app.inventory_qty_guard via app, or app.migration_mode for migrations)';
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
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
