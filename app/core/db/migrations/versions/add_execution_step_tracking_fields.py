"""Add execution step tracking fields for terminal step detection and progress calculation

Revision ID: execution_step_tracking_001
Revises: case_insensitive_email_001
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'execution_step_tracking_001'
down_revision: Union[str, None] = 'case_insensitive_email_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add total_steps to executions table to snapshot step count at creation
    # This ensures progress calculation doesn't change if steps are added/reordered later
    op.add_column('executions', sa.Column('total_steps', sa.Integer(), nullable=True))
    
    # Add is_terminal_step to execution_steps table for deterministic terminal step detection
    op.add_column('execution_steps', sa.Column('is_terminal_step', sa.Boolean(), nullable=False, server_default='false'))
    
    # Backfill total_steps for existing executions
    # Calculate from current execution_steps count
    op.execute("""
        UPDATE executions e
        SET total_steps = (
            SELECT COUNT(*) 
            FROM execution_steps es 
            WHERE es.execution_id = e.id
        )
        WHERE total_steps IS NULL
    """)
    
    # Backfill is_terminal_step for existing execution_steps
    # Mark the step with the highest step_number for each execution as terminal
    op.execute("""
        UPDATE execution_steps es
        SET is_terminal_step = true
        WHERE es.step_number = (
            SELECT MAX(es2.step_number)
            FROM execution_steps es2
            WHERE es2.execution_id = es.execution_id
        )
    """)


def downgrade() -> None:
    op.drop_column('execution_steps', 'is_terminal_step')
    op.drop_column('executions', 'total_steps')

