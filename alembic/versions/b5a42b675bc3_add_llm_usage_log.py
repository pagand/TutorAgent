"""add_llm_usage_log

Revision ID: b5a42b675bc3
Revises: f3a1c9d47b2e
Create Date: 2026-08-03

Stage 4.5: LLM spend cap. nginx's rate limit is per source IP and cannot
see user_id, so it cannot bound cost per account or globally. This table
is what app/services/llm_quota.py counts against the per-user and global
rolling-24h caps. One row is inserted per accepted hint/chat call, before
the LLM call runs.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5a42b675bc3'
down_revision = 'f3a1c9d47b2e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'llm_usage_log',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_llm_usage_log_user_created', 'llm_usage_log', ['user_id', 'created_at'])
    op.create_index('ix_llm_usage_log_created', 'llm_usage_log', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_llm_usage_log_created', table_name='llm_usage_log')
    op.drop_index('ix_llm_usage_log_user_created', table_name='llm_usage_log')
    op.drop_table('llm_usage_log')
