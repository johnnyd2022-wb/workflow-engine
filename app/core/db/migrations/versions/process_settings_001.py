"""Add a small settings JSON column to processes (workflows).

First use: fifo_auto_select, which pre-suggests the oldest in-stock lot for a manual
inventory pick at execution time (see execution-render-inputs.js), the same way sales are
already matched to batches FIFO.

Revision ID: process_settings_001
Revises: suppliers_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "process_settings_001"
down_revision = "suppliers_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "processes",
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("processes", "settings")
