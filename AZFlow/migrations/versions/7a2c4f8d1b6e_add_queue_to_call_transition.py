"""add queue to call transition

Revision ID: 7a2c4f8d1b6e
Revises: beebc699a160
Create Date: 2026-10-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7a2c4f8d1b6e"
down_revision: Union[str, Sequence[str], None] = "beebc699a160"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Record the Queue that originated a call transition."""
    op.add_column(
        "service_access_transition",
        sa.Column("queue_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_service_access_transition_queue",
        "service_access_transition",
        "queue",
        ["queue_id"],
        ["id"],
    )


def downgrade() -> None:
    """Remove call-origin Queue persistence."""
    op.drop_constraint(
        "fk_service_access_transition_queue",
        "service_access_transition",
        type_="foreignkey",
    )
    op.drop_column("service_access_transition", "queue_id")
