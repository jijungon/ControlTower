"""service_shapes · config_items — 서비스 비교표 + center config

Revision ID: b7d1e4a9c2f3
Revises: f264ab6fa6a3
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d1e4a9c2f3'
down_revision: Union[str, Sequence[str], None] = 'f264ab6fa6a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('service_shapes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('service', sa.String(), nullable=False),
    sa.Column('group_name', sa.String(), nullable=True),
    sa.Column('data', sa.Text(), nullable=False),
    sa.Column('env_hash', sa.String(), nullable=True),
    sa.Column('env_changed_at', sa.String(), nullable=True),
    sa.Column('collected_at', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('service')
    )
    op.create_table('config_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('path', sa.String(), nullable=False),
    sa.Column('data', sa.Text(), nullable=False),
    sa.Column('collected_at', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('path')
    )


def downgrade() -> None:
    op.drop_table('config_items')
    op.drop_table('service_shapes')
