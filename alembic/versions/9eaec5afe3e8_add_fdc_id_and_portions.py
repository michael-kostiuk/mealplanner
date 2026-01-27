"""add_fdc_id_and_portions

Revision ID: 9eaec5afe3e8
Revises: 04ba06917c64
Create Date: 2026-01-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9eaec5afe3e8'
down_revision: Union[str, Sequence[str], None] = '04ba06917c64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add fdc_id column to ingredients
    op.add_column('ingredients', sa.Column('fdc_id', sa.Integer(), nullable=True))
    op.create_index('ix_ingredients_fdc_id', 'ingredients', ['fdc_id'])

    # 2. Create ingredient_portions table
    op.create_table(
        'ingredient_portions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),
        sa.Column('unit', sa.String(length=50), nullable=False),
        sa.Column('gram_weight', sa.Float(), nullable=False),
        sa.Column('modifier', sa.String(length=100), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=True, default=False),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ingredient_portions_ingredient_id', 'ingredient_portions', ['ingredient_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ingredient_portions_ingredient_id', table_name='ingredient_portions')
    op.drop_table('ingredient_portions')
    op.drop_index('ix_ingredients_fdc_id', table_name='ingredients')
    op.drop_column('ingredients', 'fdc_id')
