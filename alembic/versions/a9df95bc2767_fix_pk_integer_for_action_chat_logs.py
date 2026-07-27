"""fix_pk_integer_for_action_chat_logs

Revision ID: a9df95bc2767
Revises: 73cefad687ac
Create Date: 2026-03-16 21:43:16.174300

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9df95bc2767'
down_revision: Union[str, None] = '73cefad687ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
