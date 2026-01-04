"""Fix core models enum creation

Revision ID: acf7c513c15e
Revises: merge_core_phone_001
Create Date: 2026-01-02 22:19:29.511123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'acf7c513c15e'
down_revision: Union[str, None] = 'merge_core_phone_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

