"""add_interaction_log_voided_at

Revision ID: c81f4e2a9d33
Revises: b5a42b675bc3
Create Date: 2026-08-09

Backs the admin UI's "Unlock question" repair. Before this, the only
per-student remedies were Reset Progress (wipes the whole interaction history
and mastery) and Delete User, so a student wrongly locked out of one question
mid-exam could only be fixed by destroying their data.

Stamping voided_at excludes a row from the two places that decide whether a
question is locked - the attempt cap in app/endpoints/answer.py and the history
the frontend rebuilds question state from in app/state_manager.py - while
leaving the row in place for research and CSV export.

Nullable with no default, so it is a pure metadata change: no table rewrite,
no backfill, and every existing row reads as not-voided.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c81f4e2a9d33'
down_revision = 'b5a42b675bc3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('interaction_logs', sa.Column('voided_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('interaction_logs', 'voided_at')
