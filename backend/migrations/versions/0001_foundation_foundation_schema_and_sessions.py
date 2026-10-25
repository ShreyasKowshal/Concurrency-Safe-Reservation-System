"""foundation schema and sessions

Revision ID: 0001_foundation
Revises: none (initial schema)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive initial schema; no existing application data is removed.
    op.create_table(
        "users",
        sa.Column("normalized_email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=1024), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="ATTENDEE", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("password_hash LIKE '$argon2id$%'", name=op.f("ck_users_password_hash")),
        sa.CheckConstraint("role IN ('ATTENDEE', 'ORGANIZER')", name=op.f("ck_users_role")),
        sa.CheckConstraint(
            "normalized_email = lower(btrim(normalized_email)) "
            "AND char_length(normalized_email) BETWEEN 3 AND 254",
            name=op.f("ck_users_normalized_email"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("normalized_email", name=op.f("uq_users_normalized_email")),
    )
    op.create_table(
        "events",
        sa.Column("organizer_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("location", sa.String(length=300), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("booking_closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("allocated_seats", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'CLOSED')", name=op.f("ck_events_status")
        ),
        sa.CheckConstraint(
            "allocated_seats >= 0 AND allocated_seats <= capacity",
            name=op.f("ck_events_allocation"),
        ),
        sa.CheckConstraint(
            "booking_closes_at <= starts_at AND starts_at < ends_at",
            name=op.f("ck_events_schedule"),
        ),
        sa.CheckConstraint("capacity >= 1", name=op.f("ck_events_capacity")),
        sa.CheckConstraint(
            "char_length(btrim(location)) BETWEEN 1 AND 300", name=op.f("ck_events_location")
        ),
        sa.CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 200", name=op.f("ck_events_title")
        ),
        sa.ForeignKeyConstraint(
            ["organizer_id"],
            ["users.id"],
            name=op.f("fk_events_organizer_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_organizer_id", "events", ["organizer_id"], unique=False)
    op.create_index(
        "ix_events_published_start",
        "events",
        ["starts_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column(
            "response_body",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(response_status IS NULL AND response_body IS NULL AND completed_at IS NULL) OR "
            "(response_status IS NOT NULL AND response_status BETWEEN 200 AND 499 "
            "AND response_body IS NOT NULL AND jsonb_typeof(response_body) = 'object' "
            "AND completed_at IS NOT NULL AND completed_at >= created_at)",
            name=op.f("ck_idempotency_records_completion"),
        ),
        sa.CheckConstraint(
            "key ~ '^[!-~]{1,128}$' AND octet_length(key) = char_length(key)",
            name=op.f("ck_idempotency_records_key"),
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_idempotency_records_fingerprint"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_idempotency_records_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
        sa.UniqueConstraint("user_id", "key", name=op.f("uq_idempotency_records_user_id")),
    )
    op.create_table(
        "sessions",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'ANONYMOUS' AND user_id IS NULL) OR "
            "(kind = 'AUTHENTICATED' AND user_id IS NOT NULL)",
            name=op.f("ck_sessions_kind_user"),
        ),
        sa.CheckConstraint("csrf_token ~ '^[0-9a-f]{64}$'", name=op.f("ck_sessions_csrf_token")),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_sessions_token_hash")),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_sessions_expiry")),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name=op.f("ck_sessions_revocation")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], unique=False)
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_table(
        "reservations",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="HELD", nullable=False),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'HELD' AND confirmed_at IS NULL "
            "AND cancelled_at IS NULL AND expired_at IS NULL) OR "
            "(status = 'CONFIRMED' AND confirmed_at IS NOT NULL "
            "AND cancelled_at IS NULL AND expired_at IS NULL) OR "
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL AND expired_at IS NULL) OR "
            "(status = 'EXPIRED' AND expired_at IS NOT NULL "
            "AND confirmed_at IS NULL AND cancelled_at IS NULL)",
            name=op.f("ck_reservations_state_timestamps"),
        ),
        sa.CheckConstraint(
            "cancelled_at IS NULL OR (cancelled_at >= created_at "
            "AND (confirmed_at IS NULL OR cancelled_at >= confirmed_at))",
            name=op.f("ck_reservations_cancellation_time"),
        ),
        sa.CheckConstraint(
            "confirmed_at IS NULL OR (confirmed_at >= created_at "
            "AND confirmed_at < hold_expires_at)",
            name=op.f("ck_reservations_confirmation_time"),
        ),
        sa.CheckConstraint(
            "expired_at IS NULL OR expired_at >= hold_expires_at",
            name=op.f("ck_reservations_expiration_time"),
        ),
        sa.CheckConstraint("hold_expires_at > created_at", name=op.f("ck_reservations_deadline")),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_reservations_event_id_events"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reservations_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
    )
    op.create_index(
        "ix_reservations_event_status", "reservations", ["event_id", "status"], unique=False
    )
    op.create_index(
        "ix_reservations_held_expiry",
        "reservations",
        ["hold_expires_at", "event_id"],
        unique=False,
        postgresql_where=sa.text("status = 'HELD'"),
    )
    op.create_index(
        "ix_reservations_user_history",
        "reservations",
        ["user_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "uq_reservations_active_user_event",
        "reservations",
        ["user_id", "event_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('HELD', 'CONFIRMED')"),
    )


def downgrade() -> None:
    # Downgrade is destructive; verification uses only generated disposable databases.
    op.drop_index(
        "uq_reservations_active_user_event",
        table_name="reservations",
        postgresql_where=sa.text("status IN ('HELD', 'CONFIRMED')"),
    )
    op.drop_index("ix_reservations_user_history", table_name="reservations")
    op.drop_index(
        "ix_reservations_held_expiry",
        table_name="reservations",
        postgresql_where=sa.text("status = 'HELD'"),
    )
    op.drop_index("ix_reservations_event_status", table_name="reservations")
    op.drop_table("reservations")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("idempotency_records")
    op.drop_index(
        "ix_events_published_start",
        table_name="events",
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.drop_index("ix_events_organizer_id", table_name="events")
    op.drop_table("events")
    op.drop_table("users")
