"""add_confidence_to_interaction_logs

Revision ID: 418aa98ecaec
Revises: e4b7c05f1a68
Create Date: 2026-09-20

Self-declared confidence (1-10) a student may optionally give when
submitting an answer. Telemetry only - it feeds nothing (not BKT, not hint
style selection, not intervention, not the results page). Null means the
student left it empty.
"""
from alembic import op
import sqlalchemy as sa

revision = '418aa98ecaec'
down_revision = 'e4b7c05f1a68'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'interaction_logs',
        sa.Column('confidence', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('interaction_logs', 'confidence')
