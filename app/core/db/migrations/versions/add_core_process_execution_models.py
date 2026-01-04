"""Add core process execution models

Revision ID: add_core_models_001
Revises: merge_heads_001
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ENUM

# revision identifiers, used by Alembic.
revision: str = 'add_core_models_001'
down_revision: Union[str, None] = 'merge_heads_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    
    # Create process_category enum using raw SQL with DO block to handle existence
    bind.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE process_category AS ENUM ('MANUFACTURING', 'CHEMICAL', 'PACKAGING', 'ASSEMBLY', 'OTHER');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """))
    
    # Create processes table (check if it exists first)
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'processes'
        )
    """))
    table_exists = result.scalar()
    
    if not table_exists:
        # Create table using raw SQL to avoid SQLAlchemy's enum creation event
        bind.execute(sa.text("""
            CREATE TABLE processes (
                id UUID NOT NULL PRIMARY KEY,
                org_id UUID NOT NULL,
                name VARCHAR(255) NOT NULL,
                description VARCHAR(1000),
                category process_category,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                CONSTRAINT processes_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id)
            )
        """))
        # Create index if it doesn't exist
        result = bind.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = 'ix_processes_org_id'
            )
        """))
        if not result.scalar():
            op.create_index(op.f('ix_processes_org_id'), 'processes', ['org_id'], unique=False)
    
    # Create steps table (check if it exists first)
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'steps'
        )
    """))
    table_exists = result.scalar()
    
    if not table_exists:
        op.create_table('steps',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('process_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('step_number', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=True),
    sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('outputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['process_id'], ['processes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
        # Create index if it doesn't exist
        result = bind.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = 'ix_steps_process_id'
            )
        """))
        if not result.scalar():
            op.create_index(op.f('ix_steps_process_id'), 'steps', ['process_id'], unique=False)
    
    # Create execution_status enum using raw SQL with DO block to handle existence
    bind.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE execution_status AS ENUM ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'CANCELLED');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """))
    
    # Create executions table (check if it exists first)
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'executions'
        )
    """))
    table_exists = result.scalar()
    
    if not table_exists:
        # Create table using raw SQL to avoid SQLAlchemy's enum creation event
        bind.execute(sa.text("""
            CREATE TABLE executions (
                id UUID NOT NULL PRIMARY KEY,
                org_id UUID NOT NULL,
                process_id UUID NOT NULL,
                status execution_status NOT NULL,
                started_at TIMESTAMP WITH TIME ZONE NOT NULL,
                completed_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                CONSTRAINT executions_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id),
                CONSTRAINT executions_process_id_fkey FOREIGN KEY (process_id) REFERENCES processes(id)
            )
        """))
        # Create indexes if they don't exist
        result = bind.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = 'ix_executions_org_id'
            )
        """))
        if not result.scalar():
            op.create_index(op.f('ix_executions_org_id'), 'executions', ['org_id'], unique=False)
        
        result = bind.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = 'ix_executions_process_id'
            )
        """))
        if not result.scalar():
            op.create_index(op.f('ix_executions_process_id'), 'executions', ['process_id'], unique=False)
    
    # Create execution_step_status enum using raw SQL with DO block to handle existence
    bind.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE execution_step_status AS ENUM ('PENDING', 'READY', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'SKIPPED');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """))
    
    # Create execution_steps table (check if it exists first)
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'execution_steps'
        )
    """))
    table_exists = result.scalar()
    
    if not table_exists:
        # Create table using raw SQL to avoid SQLAlchemy's enum creation event
        bind.execute(sa.text("""
            CREATE TABLE execution_steps (
                id UUID NOT NULL PRIMARY KEY,
                execution_id UUID NOT NULL,
                step_id UUID NOT NULL,
                step_number INTEGER NOT NULL,
                status execution_step_status NOT NULL,
                actual_inputs JSONB,
                actual_outputs JSONB,
                execution_data JSONB,
                started_at TIMESTAMP WITH TIME ZONE,
                completed_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                CONSTRAINT execution_steps_execution_id_fkey FOREIGN KEY (execution_id) REFERENCES executions(id),
                CONSTRAINT execution_steps_step_id_fkey FOREIGN KEY (step_id) REFERENCES steps(id)
            )
        """))
        # Create indexes if they don't exist
        result = bind.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = 'ix_execution_steps_execution_id'
            )
        """))
        if not result.scalar():
            op.create_index(op.f('ix_execution_steps_execution_id'), 'execution_steps', ['execution_id'], unique=False)
        
        result = bind.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = 'ix_execution_steps_step_id'
            )
        """))
        if not result.scalar():
            op.create_index(op.f('ix_execution_steps_step_id'), 'execution_steps', ['step_id'], unique=False)
    
    # Create inventory_items table (check if it exists first)
    result = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'inventory_items'
        )
    """))
    table_exists = result.scalar()
    
    if not table_exists:
        op.create_table('inventory_items',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('quantity', sa.String(length=50), nullable=False),
    sa.Column('unit', sa.String(length=50), nullable=False),
    sa.Column('inventory_type', sa.String(length=50), nullable=False),
    sa.Column('supplier', sa.String(length=255), nullable=True),
    sa.Column('purchase_date', sa.Date(), nullable=True),
    sa.Column('supplier_batch_number', sa.String(length=255), nullable=True),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('source_execution_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('source_execution_step_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('source_step_name', sa.String(length=255), nullable=True),
    sa.Column('extra_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ),
    sa.ForeignKeyConstraint(['source_execution_id'], ['executions.id'], ),
    sa.ForeignKeyConstraint(['source_execution_step_id'], ['execution_steps.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
        # Create indexes if they don't exist
        result = bind.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = 'ix_inventory_items_org_id'
            )
        """))
        if not result.scalar():
            op.create_index(op.f('ix_inventory_items_org_id'), 'inventory_items', ['org_id'], unique=False)
        
        result = bind.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = 'ix_inventory_items_source_execution_id'
            )
        """))
        if not result.scalar():
            op.create_index(op.f('ix_inventory_items_source_execution_id'), 'inventory_items', ['source_execution_id'], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_index(op.f('ix_inventory_items_source_execution_id'), table_name='inventory_items')
    op.drop_index(op.f('ix_inventory_items_org_id'), table_name='inventory_items')
    op.drop_table('inventory_items')
    
    op.drop_index(op.f('ix_execution_steps_step_id'), table_name='execution_steps')
    op.drop_index(op.f('ix_execution_steps_execution_id'), table_name='execution_steps')
    op.drop_table('execution_steps')
    sa.Enum(name='execution_step_status').drop(op.get_bind(), checkfirst=True)
    
    op.drop_index(op.f('ix_executions_process_id'), table_name='executions')
    op.drop_index(op.f('ix_executions_org_id'), table_name='executions')
    op.drop_table('executions')
    sa.Enum(name='execution_status').drop(op.get_bind(), checkfirst=True)
    
    op.drop_index(op.f('ix_steps_process_id'), table_name='steps')
    op.drop_table('steps')
    
    op.drop_index(op.f('ix_processes_org_id'), table_name='processes')
    op.drop_table('processes')
    sa.Enum(name='process_category').drop(op.get_bind(), checkfirst=True)

