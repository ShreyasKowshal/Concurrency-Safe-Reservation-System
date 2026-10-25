"""PostgreSQL schema. Reservation mutations must later follow the event-lock protocol."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Role(StrEnum):
    ATTENDEE = "ATTENDEE"
    ORGANIZER = "ORGANIZER"


class SessionKind(StrEnum):
    ANONYMOUS = "ANONYMOUS"
    AUTHENTICATED = "AUTHENTICATED"


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
        }
    )


class Identity:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Updated:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Identity, Updated, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("normalized_email"),
        CheckConstraint("role IN ('ATTENDEE', 'ORGANIZER')", name="role"),
        CheckConstraint(
            "normalized_email = lower(btrim(normalized_email)) "
            "AND char_length(normalized_email) BETWEEN 3 AND 254",
            name="normalized_email",
        ),
        CheckConstraint("password_hash LIKE '$argon2id$%'", name="password_hash"),
    )

    normalized_email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(1024))
    role: Mapped[str] = mapped_column(String(16), server_default=Role.ATTENDEE)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class SessionRecord(Identity, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint(
            "(kind = 'ANONYMOUS' AND user_id IS NULL) OR "
            "(kind = 'AUTHENTICATED' AND user_id IS NOT NULL)",
            name="kind_user",
        ),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash"),
        CheckConstraint("csrf_token ~ '^[0-9a-f]{64}$'", name="csrf_token"),
        CheckConstraint("expires_at > created_at", name="expiry"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation"),
        Index("ix_sessions_expires_at", "expires_at"),
        Index("ix_sessions_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64))
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Identity, Updated, Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'CLOSED')", name="status"),
        CheckConstraint("capacity >= 1", name="capacity"),
        CheckConstraint("allocated_seats >= 0 AND allocated_seats <= capacity", name="allocation"),
        CheckConstraint("booking_closes_at <= starts_at AND starts_at < ends_at", name="schedule"),
        CheckConstraint("char_length(btrim(title)) BETWEEN 1 AND 200", name="title"),
        CheckConstraint("char_length(btrim(location)) BETWEEN 1 AND 300", name="location"),
        Index("ix_events_organizer_id", "organizer_id"),
        Index(
            "ix_events_published_start",
            "starts_at",
            "id",
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    organizer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, server_default="")
    location: Mapped[str] = mapped_column(String(300))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    booking_closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), server_default="DRAFT")
    capacity: Mapped[int] = mapped_column(Integer)
    allocated_seats: Mapped[int] = mapped_column(Integer, server_default="0")


class Reservation(Identity, Updated, Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("hold_expires_at > created_at", name="deadline"),
        CheckConstraint(
            "(status = 'HELD' AND confirmed_at IS NULL "
            "AND cancelled_at IS NULL AND expired_at IS NULL) OR "
            "(status = 'CONFIRMED' AND confirmed_at IS NOT NULL "
            "AND cancelled_at IS NULL AND expired_at IS NULL) OR "
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL AND expired_at IS NULL) OR "
            "(status = 'EXPIRED' AND expired_at IS NOT NULL "
            "AND confirmed_at IS NULL AND cancelled_at IS NULL)",
            name="state_timestamps",
        ),
        CheckConstraint(
            "confirmed_at IS NULL OR (confirmed_at >= created_at "
            "AND confirmed_at < hold_expires_at)",
            name="confirmation_time",
        ),
        CheckConstraint(
            "cancelled_at IS NULL OR (cancelled_at >= created_at AND "
            "(confirmed_at IS NULL OR cancelled_at >= confirmed_at))",
            name="cancellation_time",
        ),
        CheckConstraint(
            "expired_at IS NULL OR expired_at >= hold_expires_at", name="expiration_time"
        ),
        Index(
            "uq_reservations_active_user_event",
            "user_id",
            "event_id",
            unique=True,
            postgresql_where=text("status IN ('HELD', 'CONFIRMED')"),
        ),
        Index("ix_reservations_user_history", "user_id", "created_at", "id"),
        Index("ix_reservations_event_status", "event_id", "status"),
        Index(
            "ix_reservations_held_expiry",
            "hold_expires_at",
            "event_id",
            postgresql_where=text("status = 'HELD'"),
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), server_default="HELD")
    hold_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Identity, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("user_id", "key"),
        CheckConstraint(
            "key ~ '^[!-~]{1,128}$' AND octet_length(key) = char_length(key)", name="key"
        ),
        CheckConstraint("request_fingerprint ~ '^[0-9a-f]{64}$'", name="fingerprint"),
        CheckConstraint(
            "(response_status IS NULL AND response_body IS NULL AND completed_at IS NULL) OR "
            "(response_status IS NOT NULL AND response_status BETWEEN 200 AND 499 "
            "AND response_body IS NOT NULL "
            "AND jsonb_typeof(response_body) = 'object' AND completed_at IS NOT NULL "
            "AND completed_at >= created_at)",
            name="completion",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
