"""host_status — 서버가 스스로 적는 상태 파일(IdP 서버 status.json)을 수집기가 읽어 올린 마지막 모습

Revision ID: e5a1c3f9b2d4
Revises: d7b3f9a2c6e1
Create Date: 2026-10-21 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a1c3f9b2d4'
down_revision: Union[str, Sequence[str], None] = 'd7b3f9a2c6e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('host_status',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('reader', sa.String(), nullable=True),
    sa.Column('received_at', sa.String(), nullable=True),
    sa.Column('read_ok', sa.Boolean(), nullable=False),
    sa.Column('read_error', sa.Text(), nullable=True),
    sa.Column('written_at', sa.String(), nullable=True),
    sa.Column('host', sa.String(), nullable=True),
    sa.Column('interval_seconds', sa.Integer(), nullable=True),
    sa.Column('ok', sa.Boolean(), nullable=True),
    sa.Column('problems', sa.Text(), nullable=True),
    sa.Column('unread', sa.Text(), nullable=True),
    sa.Column('signals', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source')
    )


def downgrade() -> None:
    op.drop_table('host_status')
