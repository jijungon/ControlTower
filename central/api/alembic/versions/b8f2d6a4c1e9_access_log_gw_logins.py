"""access_log 에 gw 접속 기록 칸 — gw-logins.jsonl 을 같은 표의 source 'idp-gw' 줄로(칸 셋 더하기만, 모두 비어도 됨)

Revision ID: b8f2d6a4c1e9
Revises: a3c9e5f1b7d2
Create Date: 2026-10-28 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8f2d6a4c1e9'
down_revision: Union[str, Sequence[str], None] = 'a3c9e5f1b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('access_log') as batch:
        batch.add_column(sa.Column('reports', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('gws', sa.Text(), nullable=True))
        batch.add_column(sa.Column('bad_gws', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('access_log') as batch:
        batch.drop_column('bad_gws')
        batch.drop_column('gws')
        batch.drop_column('reports')
