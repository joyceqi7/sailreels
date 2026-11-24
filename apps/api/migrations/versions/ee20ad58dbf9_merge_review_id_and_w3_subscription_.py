"""merge review_id and W3 subscription heads

Revision ID: ee20ad58dbf9
Revises: 90a3c8d2e641, b6fe1f970e17
Create Date: 2026-10-28 16:44:31.800852

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'ee20ad58dbf9'
down_revision: Union[str, Sequence[str], None] = ('90a3c8d2e641', 'b6fe1f970e17')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
