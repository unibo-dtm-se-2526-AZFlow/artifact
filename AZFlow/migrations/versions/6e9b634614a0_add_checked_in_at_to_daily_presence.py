"""add checked in at to daily presence

Revision ID: 6e9b634614a0
Revises: 6d3c09e02018
Create Date: 2026-09-26 01:47:58.433949
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "6e9b634614a0"
down_revision: Union[str, Sequence[str], None] = "6d3c09e02018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store when the DailyPresence was first created."""
    op.add_column(
        "daily_presence",
        sa.Column(
            "checked_in_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    """Remove the DailyPresence check-in timestamp."""
    op.drop_column("daily_presence", "checked_in_at")
