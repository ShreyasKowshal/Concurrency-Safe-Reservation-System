"""Support ordered bounded cleanup after the event lock.

Revision ID: 0002_worker_expiry
Revises: 0001_foundation
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_worker_expiry"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_reservations_event_held_expiry",
        "reservations",
        ["event_id", "hold_expires_at", "id"],
        postgresql_where=sa.text("status = 'HELD'"),
    )


def downgrade() -> None:
    op.drop_index("ix_reservations_event_held_expiry", table_name="reservations")
