"""add_chat_chatiq_flags_to_participants

Revision ID: 611aa5e19916
Revises: 418aa98ecaec
Create Date: 2026-09-20

Two new per-participant experiment flags on top of the existing group/
intervention assignment: chat_enabled and chatiq_enabled. Three arms in use:
chat off; chat on, ChatIQ off; chat on, ChatIQ on. server_default=true so
every existing row (seeded before this column existed) keeps chat and
ChatIQ on, matching prior behavior.
"""
from alembic import op
import sqlalchemy as sa

revision = '611aa5e19916'
down_revision = '418aa98ecaec'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'participants',
        sa.Column('chat_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'participants',
        sa.Column('chatiq_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column('participants', 'chatiq_enabled')
    op.drop_column('participants', 'chat_enabled')
