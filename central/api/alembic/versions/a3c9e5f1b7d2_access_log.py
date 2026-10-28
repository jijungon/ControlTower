"""access_log — 금고(IdP) 접속 기록 요약 파일을 수집기가 읽어 올린 마지막 모습(source 마다 한 줄)

Revision ID: a3c9e5f1b7d2
Revises: e5a1c3f9b2d4
Create Date: 2026-10-28 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c9e5f1b7d2'
down_revision: Union[str, Sequence[str], None] = 'e5a1c3f9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('access_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('reader', sa.String(), nullable=True),
    sa.Column('received_at', sa.String(), nullable=True),
    sa.Column('read_ok', sa.Boolean(), nullable=False),
    sa.Column('read_error', sa.Text(), nullable=True),
    sa.Column('written_at', sa.String(), nullable=True),
    sa.Column('host', sa.String(), nullable=True),
    sa.Column('interval_seconds', sa.Integer(), nullable=True),
    sa.Column('window_days', sa.Integer(), nullable=True),
    sa.Column('audit_ok', sa.Boolean(), nullable=True),
    sa.Column('audit_reason', sa.Text(), nullable=True),
    sa.Column('files_read', sa.Integer(), nullable=True),
    sa.Column('lines_read', sa.Integer(), nullable=True),
    sa.Column('source_bad_lines', sa.Integer(), nullable=True),
    sa.Column('header_events', sa.Integer(), nullable=True),
    sa.Column('event_lines', sa.Integer(), nullable=True),
    sa.Column('bad_lines', sa.Integer(), nullable=False),
    sa.Column('truncated', sa.Boolean(), nullable=False),
    sa.Column('events', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source')
    )


def downgrade() -> None:
    op.drop_table('access_log')
