"""add is_leftover to meal plan entries

Revision ID: b7c3d1e4f5a6
Revises: 99af4a25aef9
Create Date: 2026-10-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c3d1e4f5a6'
down_revision: Union[str, Sequence[str], None] = '99af4a25aef9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'meal_plan_entries',
        sa.Column('is_leftover', sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('meal_plan_entries', 'is_leftover')
