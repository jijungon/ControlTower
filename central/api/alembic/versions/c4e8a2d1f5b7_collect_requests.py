"""collect_requests · collectors — 화면 [다시 수집] 버튼의 요청 + 수집기 마지막 확인 시각

Revision ID: c4e8a2d1f5b7
Revises: b7d1e4a9c2f3
Create Date: 2026-10-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8a2d1f5b7'
down_revision: Union[str, Sequence[str], None] = 'b7d1e4a9c2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('collect_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('requested_at', sa.String(), nullable=True),
    sa.Column('started_at', sa.String(), nullable=True),
    sa.Column('finished_at', sa.String(), nullable=True),
    sa.Column('collector', sa.String(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('collectors',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('mode', sa.String(), nullable=True),
    sa.Column('last_seen_at', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )


def downgrade() -> None:
    op.drop_table('collectors')
    op.drop_table('collect_requests')
