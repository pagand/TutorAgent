"""Add hint_text to interaction log

Revision ID: bd54c188910a
Revises: d67a18d1e658
Create Date: 2025-10-03 17:07:33.563744

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd54c188910a'
down_revision: Union[str, None] = 'd67a18d1e658'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interaction_logs', sa.Column('hint_text', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('interaction_logs', 'hint_text')
