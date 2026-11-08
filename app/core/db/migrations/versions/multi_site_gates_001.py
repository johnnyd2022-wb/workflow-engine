"""Multiple sites behind a subscription, not an internal flag (GL-P07).

`organisations.multiple_site_operations_enabled` was an internal staged-release flag nothing in
the app could set. Working at additional sites now needs the deployment flag
(`[features] multi_site_enabled`), the organisation's `multi_site` subscription and its own
Settings switch. An organisation that had the old flag on keeps access: it is given the
subscription before the column goes.

Revision ID: multi_site_gates_001
Revises: contract_dispatch_001
"""

import sqlalchemy as sa
from alembic import op

revision = "multi_site_gates_001"
down_revision = "contract_dispatch_001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO feature_subscriptions (id, org_id, feature_key, active, granted_at, notes)
        SELECT gen_random_uuid(), o.id, 'multi_site', true, now(), 'Carried over from multiple_site_operations_enabled'
        FROM organisations o
        WHERE o.multiple_site_operations_enabled
        ON CONFLICT (org_id, feature_key) DO UPDATE SET active = true
        """
    )
    op.drop_column("organisations", "multiple_site_operations_enabled")


def downgrade():
    op.add_column(
        "organisations",
        sa.Column("multiple_site_operations_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        UPDATE organisations o SET multiple_site_operations_enabled = true
        FROM feature_subscriptions s
        WHERE s.org_id = o.id AND s.feature_key = 'multi_site' AND s.active
        """
    )
