"""Add is_draft to processes

Revision ID: add_is_draft_001
Revises: add_execution_prompts_001
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_is_draft_001'
down_revision: Union[str, None] = 'add_execution_prompts_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    
    # Check if is_draft column already exists
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'processes' 
            AND column_name = 'is_draft'
        )
    """))
    column_exists = result.scalar()
    
    if not column_exists:
        # Add is_draft column to processes table
        bind.execute(sa.text("""
            ALTER TABLE processes 
            ADD COLUMN is_draft BOOLEAN NOT NULL DEFAULT false
        """))
        
        # Create index for faster queries on draft processes
        bind.execute(sa.text("""
            CREATE INDEX IF NOT EXISTS idx_processes_is_draft 
            ON processes(is_draft)
        """))


def downgrade() -> None:
    bind = op.get_bind()
    
    # Check if is_draft column exists before dropping
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'processes' 
            AND column_name = 'is_draft'
        )
    """))
    column_exists = result.scalar()
    
    if column_exists:
        # Drop index first
        bind.execute(sa.text("""
            DROP INDEX IF EXISTS idx_processes_is_draft
        """))
        
        # Remove is_draft column from processes table
        bind.execute(sa.text("""
            ALTER TABLE processes 
            DROP COLUMN is_draft
        """))
