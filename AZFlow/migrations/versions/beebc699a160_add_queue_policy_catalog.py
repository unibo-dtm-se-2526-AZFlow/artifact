"""add queue policy catalog

Revision ID: beebc699a160
Revises: 639159279093
Create Date: 2026-09-26 23:32:13.771436

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "beebc699a160"
down_revision: Union[str, Sequence[str], None] = "639159279093"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICIES = (
    (
        "BY_ARRIVAL",
        "By arrival",
        "Order patients by check-in time.",
    ),
    (
        "BY_APPOINTMENT",
        "By appointment",
        "Order patients by scheduled appointment time.",
    ),
)


def upgrade() -> None:
    """Add the Queue policy reference catalog and link queues to it."""
    policy_table = op.create_table(
        "queue_policy",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.bulk_insert(
        policy_table,
        [
            {"code": code, "label": label, "description": description}
            for code, label, description in POLICIES
        ],
    )
    op.drop_constraint("queue_policy_check", "queue", type_="check")
    op.create_foreign_key(
        "fk_queue_policy",
        "queue",
        "queue_policy",
        ["policy"],
        ["code"],
    )


def downgrade() -> None:
    """Restore the Queue policy check constraint."""
    op.drop_constraint("fk_queue_policy", "queue", type_="foreignkey")
    op.create_check_constraint(
        "queue_policy_check",
        "queue",
        "policy IN ('BY_ARRIVAL', 'BY_APPOINTMENT')",
    )
    op.drop_table("queue_policy")
