"""drama media metadata + episode cover pic

Revision ID: 2b7bc93cf3ca
Revises: 7220aa6cd5de
Create Date: 2026-10-12 11:24:55.820979

Hand-adjusted after autogenerate: the new NOT NULL columns need server defaults, otherwise adding
them to a table that already has rows fails on Postgres.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b7bc93cf3ca'
down_revision: Union[str, Sequence[str], None] = '7220aa6cd5de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('dramas', sa.Column('language', sa.String(length=16), nullable=False,
                                      server_default='en'))
    op.add_column('dramas', sa.Column('year', sa.Integer(), nullable=False, server_default='2026'))
    # 1 AIGC, 2 anime, 3 dubbed, 4 localised live action
    op.add_column('dramas', sa.Column('drama_type', sa.Integer(), nullable=False, server_default='4'))
    op.add_column('dramas', sa.Column('tags', sa.JSON(), nullable=False,
                                      server_default=sa.text("'[]'::json")))
    op.add_column('dramas', sa.Column('cover_pic_ids', sa.JSON(), nullable=False,
                                      server_default=sa.text("'[]'::json")))
    op.add_column('episodes', sa.Column('cover_pic_id', sa.String(length=128), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('episodes', 'cover_pic_id')
    op.drop_column('dramas', 'cover_pic_ids')
    op.drop_column('dramas', 'tags')
    op.drop_column('dramas', 'drama_type')
    op.drop_column('dramas', 'year')
    op.drop_column('dramas', 'language')
