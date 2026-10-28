"""idp_people — 사람 이름표(Authentik 의 server-admin · developer)를 수집기가 읽어 올린 마지막 모습(source 마다 한 줄)

Revision ID: c1f7a3e9d5b2
Revises: a3c9e5f1b7d2
Create Date: 2026-10-28 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1f7a3e9d5b2'
down_revision: Union[str, Sequence[str], None] = 'a3c9e5f1b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('idp_people',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('reader', sa.String(), nullable=True),
    sa.Column('received_at', sa.String(), nullable=True),
    sa.Column('read_ok', sa.Boolean(), nullable=False),
    sa.Column('read_error', sa.Text(), nullable=True),
    sa.Column('written_at', sa.String(), nullable=True),
    sa.Column('host', sa.String(), nullable=True),
    sa.Column('interval_seconds', sa.Integer(), nullable=True),
    sa.Column('origin', sa.String(), nullable=True),
    sa.Column('list_ok', sa.Boolean(), nullable=True),
    sa.Column('list_reason', sa.Text(), nullable=True),
    sa.Column('groups', sa.Text(), nullable=True),
    sa.Column('header_people', sa.Integer(), nullable=True),
    sa.Column('person_lines', sa.Integer(), nullable=True),
    sa.Column('bad_lines', sa.Integer(), nullable=False),
    sa.Column('truncated', sa.Boolean(), nullable=False),
    sa.Column('people', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source')
    )


def downgrade() -> None:
    op.drop_table('idp_people')
