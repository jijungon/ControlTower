"""access_log 에 서버 접속 기록 칸 — server-logins.jsonl 을 같은 표의 source 'idp-server' 줄로(칸 둘 더하기만, 모두 비어도 됨)

Revision ID: d4e7a1c9b3f6
Revises: b8f2d6a4c1e9
Create Date: 2026-10-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e7a1c9b3f6'
down_revision: Union[str, Sequence[str], None] = 'b8f2d6a4c1e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('access_log') as batch:
        batch.add_column(sa.Column('servers', sa.Text(), nullable=True))
        batch.add_column(sa.Column('bad_servers', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('access_log') as batch:
        batch.drop_column('bad_servers')
        batch.drop_column('servers')
