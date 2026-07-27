"""Add consecutive_skips to SkillMastery

Revision ID: 979e0273b7e4
Revises: bd54c188910a
Create Date: 2025-10-26 22:23:40.136352

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '979e0273b7e4'
down_revision: Union[str, None] = 'bd54c188910a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('skill_mastery', sa.Column('consecutive_skips', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('skill_mastery', 'consecutive_skips')
