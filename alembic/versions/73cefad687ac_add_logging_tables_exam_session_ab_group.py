"""add_logging_tables_exam_session_ab_group

Revision ID: 73cefad687ac
Revises: 979e0273b7e4
Create Date: 2026-03-16 21:41:23.223779

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '73cefad687ac'
down_revision: Union[str, None] = '979e0273b7e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'exam_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), unique=True, index=True, nullable=False),
        sa.Column('session_id', sa.String(), index=True, nullable=True),
        sa.Column('exam_start_ms', sa.BigInteger(), nullable=False),
        sa.Column('exam_duration_ms', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'user_action_logs',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('session_id', sa.String(), index=True, nullable=True),
        sa.Column('timestamp', sa.DateTime(), index=True, nullable=True),
        sa.Column('action_type', sa.String(), index=True, nullable=False),
        sa.Column('question_number', sa.Integer(), index=True, nullable=True),
        sa.Column('action_data', sa.JSON(), nullable=True),
    )
    op.create_table(
        'chat_logs',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('session_id', sa.String(), index=True, nullable=True),
        sa.Column('question_number', sa.Integer(), index=True, nullable=True),
        sa.Column('timestamp', sa.DateTime(), index=True, nullable=True),
        sa.Column('user_message', sa.Text(), nullable=False),
        sa.Column('tutor_response', sa.Text(), nullable=False),
    )
    op.create_table(
        'intervention_logs',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('session_id', sa.String(), index=True, nullable=True),
        sa.Column('question_number', sa.Integer(), index=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(), index=True, nullable=True),
        sa.Column('time_on_question_ms', sa.Integer(), nullable=False),
        sa.Column('mastery_at_trigger', sa.Float(), nullable=True),
        sa.Column('accepted', sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('intervention_logs')
    op.drop_table('chat_logs')
    op.drop_table('user_action_logs')
    op.drop_table('exam_sessions')
