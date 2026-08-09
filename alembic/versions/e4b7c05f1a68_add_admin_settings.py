"""add_admin_settings

Revision ID: e4b7c05f1a68
Revises: c81f4e2a9d33
Create Date: 2026-08-09

Key/value store for overrides an admin can change live from the admin UI,
without an SSM session, a .env edit and an api restart under time pressure.

Only the two LLM spend caps (LLM_MAX_CALLS_PER_DAY,
LLM_MAX_CALLS_PER_USER_PER_DAY) use it today. A table rather than process
state on purpose: process state would silently revert on
`docker compose restart api`, and a raised cap dropping back mid-exam would
re-throttle students with nobody noticing.

Starts empty. An absent key means "no override", and app/services/llm_quota.py
falls through to the value from settings, so this table existing changes
nothing until an admin actually sets something.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e4b7c05f1a68'
down_revision = 'c81f4e2a9d33'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'admin_settings',
        sa.Column('key', sa.String(), primary_key=True),
        sa.Column('value', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('admin_settings')
