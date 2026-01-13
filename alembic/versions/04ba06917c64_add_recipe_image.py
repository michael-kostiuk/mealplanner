"""add_recipe_image

Revision ID: 04ba06917c64
Revises: 6ae97a49d694
Create Date: 2026-01-12 21:05:00.239161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '04ba06917c64'
down_revision: Union[str, Sequence[str], None] = '6ae97a49d694'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('recipes', sa.Column('image_url', sa.String(500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('recipes', 'image_url')
