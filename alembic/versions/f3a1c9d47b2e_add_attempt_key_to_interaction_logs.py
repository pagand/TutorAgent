"""add_attempt_key_to_interaction_logs

Revision ID: f3a1c9d47b2e
Revises: ce7c35f16ff5
Create Date: 2026-07-26

Stage 1a: answer idempotency. Adds attempt_key to interaction_logs so a
lost-response retry of POST /answer/ can be detected and deduped instead
of being recorded as a second, distinct attempt.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3a1c9d47b2e'
down_revision = 'ce7c35f16ff5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'interaction_logs',
        sa.Column('attempt_key', sa.String(), nullable=True),
    )
    op.create_index(
        'ux_interaction_logs_user_question_attemptkey',
        'interaction_logs',
        ['user_id', 'question_id', 'attempt_key'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ux_interaction_logs_user_question_attemptkey', table_name='interaction_logs')
    op.drop_column('interaction_logs', 'attempt_key')
