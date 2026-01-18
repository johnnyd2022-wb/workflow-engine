"""Add execution_prompts to steps

Revision ID: add_execution_prompts_001
Revises: add_core_models_001
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_execution_prompts_001'
down_revision: Union[str, None] = 'add_core_models_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    
    # Check if execution_prompts column already exists
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'steps' 
            AND column_name = 'execution_prompts'
        )
    """))
    column_exists = result.scalar()
    
    if not column_exists:
        # Add execution_prompts column to steps table
        bind.execute(sa.text("""
            ALTER TABLE steps 
            ADD COLUMN execution_prompts JSONB NOT NULL DEFAULT '[]'::jsonb
        """))


def downgrade() -> None:
    bind = op.get_bind()
    
    # Check if execution_prompts column exists before dropping
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'steps' 
            AND column_name = 'execution_prompts'
        )
    """))
    column_exists = result.scalar()
    
    if column_exists:
        # Remove execution_prompts column from steps table
        bind.execute(sa.text("""
            ALTER TABLE steps 
            DROP COLUMN execution_prompts
        """))
