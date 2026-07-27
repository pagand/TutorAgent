"""add_participants_and_submitted_at

Revision ID: ce7c35f16ff5
Revises: 61011d77efc7
Create Date: 2026-05-28

Phase 2: token-based participant access.
- Creates participants table (pre-registered exam participants).
- Adds submitted_at to exam_sessions (authoritative completion flag).
"""
from alembic import op
import sqlalchemy as sa

revision = 'ce7c35f16ff5'
down_revision = '61011d77efc7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'participants',
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('identifier', sa.String(), nullable=False),
        sa.Column('group', sa.String(), nullable=False),
        sa.Column('intervention', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='unused'),
        sa.Column('active_session_id', sa.String(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('token'),
    )
    op.create_index('ix_participants_token', 'participants', ['token'])
    op.create_index('ix_participants_identifier', 'participants', ['identifier'])

    op.add_column(
        'exam_sessions',
        sa.Column('submitted_at', sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('exam_sessions', 'submitted_at')
    op.drop_index('ix_participants_identifier', table_name='participants')
    op.drop_index('ix_participants_token', table_name='participants')
    op.drop_table('participants')
