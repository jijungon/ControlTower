"""collect_requests.trigger · collectors.schedule — 매일 자동 수집(자동/버튼 구분, 수집기의 자동 시각)

Revision ID: d7b3f9a2c6e1
Revises: c4e8a2d1f5b7
Create Date: 2026-10-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7b3f9a2c6e1'
down_revision: Union[str, Sequence[str], None] = 'c4e8a2d1f5b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('collect_requests', sa.Column('trigger', sa.String(), nullable=True))
    op.add_column('collectors', sa.Column('schedule', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('collectors', 'schedule')
    op.drop_column('collect_requests', 'trigger')
