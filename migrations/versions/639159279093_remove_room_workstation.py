"""remove room workstation

Revision ID: 639159279093
Revises: 6e9b634614a0
Create Date: 2026-09-26 02:26:48.956144

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '639159279093'
down_revision: Union[str, Sequence[str], None] = '6e9b634614a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("room_workstation")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "room_workstation",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["room.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id"),
    )
