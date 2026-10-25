"""One durable command transaction: key claim -> event lock -> reservation rows.

No process-local locks or retries of uncertain commits. A caller retries the same key.
Security exceptions roll back claims; business conflicts commit cleanup and their outcome.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, true, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from csrs.auth.dependencies import require_attendee, require_owner
from csrs.auth.errors import authentication_required
from csrs.auth.service import database_time, require_session
from csrs.events.errors import EventError
from csrs.events.pagination import decode_cursor, encode_cursor
from csrs.models import Event, IdempotencyRecord, Reservation, SessionKind, User
from csrs.reservations.schemas import Availability, ReservationPage, ReservationResponse
from csrs.reservations.transitions import expire_due_holds


@dataclass(frozen=True)
class CommandReply:
    status: int
    body: dict
    replayed: bool = False


def fingerprint(path: str) -> str:
    # All current commands have POST plus a validated empty JSON object.
    canonical = json.dumps(["POST", path, {}], separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _actor(db: Session, cookie: str | None, csrf: str | None) -> User:
    record = require_session(db, cookie, csrf, SessionKind.AUTHENTICATED)
    user = db.get(User, record.user_id, populate_existing=True)
    if user is None or not user.is_active:
        raise authentication_required()
    return require_attendee(user)


def _not_found() -> EventError:
    return EventError(404, "NOT_FOUND", "Resource not found.")


def _owned_reservation(db: Session, reservation_id: UUID, actor: User) -> Reservation:
    row = db.get(Reservation, reservation_id, populate_existing=True)
    if row is None:
        raise _not_found()
    require_owner(row.user_id, actor)
    return row


def representation(row: Reservation, now: datetime) -> ReservationResponse:
    status = "EXPIRED" if row.status == "HELD" and row.hold_expires_at <= now else row.status
    return ReservationResponse(
        id=row.id,
        event_id=row.event_id,
        status=status,
        created_at=row.created_at,
        hold_expires_at=row.hold_expires_at,
        confirmed_at=row.confirmed_at,
        cancelled_at=row.cancelled_at,
        expired_at=row.expired_at,
        server_time=now,
    )


def conflict(code: str, message: str) -> CommandReply:
    return CommandReply(409, {"error": {"code": code, "message": message}})


def _apply(
    db: Session,
    event: Event,
    actor: User,
    action: str,
    row: Reservation | None,
    now: datetime,
    ttl_seconds: int,
) -> CommandReply:
    if action == "hold":
        if event.status != "PUBLISHED" or event.booking_closes_at <= now:
            return conflict("BOOKING_CLOSED", "This event is not open for booking.")
        active = db.scalar(
            select(Reservation.id).where(
                Reservation.event_id == event.id,
                Reservation.user_id == actor.id,
                Reservation.status.in_(["HELD", "CONFIRMED"]),
            )
        )
        if active is not None:
            return conflict("ACTIVE_RESERVATION_EXISTS", "An active reservation already exists.")
        if event.allocated_seats >= event.capacity:
            return conflict("EVENT_FULL", "No seats are available.")
        row = Reservation(
            event_id=event.id,
            user_id=actor.id,
            status="HELD",
            created_at=now,
            updated_at=now,
            hold_expires_at=min(now + timedelta(seconds=ttl_seconds), event.booking_closes_at),
        )
        db.add(row)
        db.flush()  # Still uncommitted; a failure here must roll back the entire command.
        event.allocated_seats += 1
    elif action == "confirm":
        if row.status == "EXPIRED":
            return conflict("HOLD_EXPIRED", "The reservation hold has expired.")
        if row.status == "CANCELLED":
            return conflict("INVALID_RESERVATION_STATE", "A cancelled reservation cannot confirm.")
        if row.status == "HELD":
            row.status, row.confirmed_at = "CONFIRMED", now
            row.updated_at = now
    elif action == "cancel":
        if row.status == "CONFIRMED" and now >= event.starts_at:
            return conflict("CANCELLATION_CLOSED", "Cancellation closes when the event starts.")
        if row.status in {"HELD", "CONFIRMED"}:
            row.status, row.cancelled_at = "CANCELLED", now
            row.updated_at = now
            event.allocated_seats -= 1
    else:
        raise ValueError("Unknown reservation command")
    db.flush()
    return CommandReply(
        201 if action == "hold" else 200, representation(row, now).model_dump(mode="json")
    )


def command(
    db: Session,
    cookie: str | None,
    csrf: str | None,
    resource_id: UUID,
    action: str,
    key: str,
    ttl_seconds: int = 300,
) -> CommandReply:
    path = (
        f"/api/v1/events/{resource_id}/holds"
        if action == "hold"
        else f"/api/v1/reservations/{resource_id}/{action}"
    )
    digest = fingerprint(path)
    with db.begin():
        actor = _actor(db, cookie, csrf)
        event_id = (
            resource_id if action == "hold" else _owned_reservation(db, resource_id, actor).event_id
        )
        claimed = db.scalar(
            insert(IdempotencyRecord)
            .values(
                user_id=actor.id,
                key=key,
                request_fingerprint=digest,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "key"])
            .returning(IdempotencyRecord.id)
        )
        # A duplicate insert may have waited for another transaction. Recheck before replay.
        actor = _actor(db, cookie, csrf)
        if action != "hold":
            _owned_reservation(db, resource_id, actor)
        record = db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == actor.id,
                IdempotencyRecord.key == key,
            )
        )
        if record.request_fingerprint != digest:
            return conflict("IDEMPOTENCY_KEY_REUSED", "This key was used for another request.")
        if claimed is None:
            # Pending claims cannot be committed by this service.
            if record.completed_at is None:
                raise RuntimeError("A committed idempotency claim has no outcome")
            return CommandReply(record.response_status, record.response_body, replayed=True)
        event = db.scalar(
            select(Event)
            .where(Event.id == event_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if event is None:
            raise _not_found()
        actor = _actor(db, cookie, csrf)
        if action != "hold":
            _owned_reservation(db, resource_id, actor)
        now = database_time(db)
        expire_due_holds(db, event, now)
        row = None if action == "hold" else _owned_reservation(db, resource_id, actor)
        reply = _apply(db, event, actor, action, row, now, ttl_seconds)
        record.response_status = reply.status
        record.response_body = reply.body
        record.completed_at = now
        db.flush()
    return reply


def get_reservation(db: Session, reservation_id: UUID, user: User) -> ReservationResponse:
    with db.begin():
        row = _owned_reservation(db, reservation_id, user)
        return representation(row, database_time(db))


def list_reservations(db: Session, user: User, limit: int, cursor: str | None) -> ReservationPage:
    with db.begin():
        scope = f"reservations:{user.id}"
        statement = select(Reservation).where(Reservation.user_id == user.id)
        if cursor is not None:
            instant, row_id = decode_cursor(cursor, scope)
            statement = statement.where(
                tuple_(Reservation.created_at, Reservation.id) > tuple_(instant, row_id)
            )
        rows = list(
            db.scalars(statement.order_by(Reservation.created_at, Reservation.id).limit(limit + 1))
        )
        now = database_time(db)
        return ReservationPage(
            items=[representation(row, now) for row in rows[:limit]],
            next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id, scope)
            if len(rows) > limit
            else None,
        )


def availability(db: Session, event_id: UUID) -> Availability:
    with db.begin():
        # Materialized one-row CTE samples actual time once; one statement has one MVCC snapshot.
        instant = (
            select(func.clock_timestamp().label("as_of")).cte("instant").prefix_with("MATERIALIZED")
        )
        occupied = (
            select(func.count())
            .select_from(Reservation)
            .where(
                Reservation.event_id == Event.id,
                (Reservation.status == "CONFIRMED")
                | (
                    (Reservation.status == "HELD") & (Reservation.hold_expires_at > instant.c.as_of)
                ),
            )
            .correlate(Event, instant)
            .scalar_subquery()
        )
        row = db.execute(
            select(
                Event.id,
                Event.capacity,
                (Event.capacity - occupied).label("available_seats"),
                instant.c.as_of,
            )
            .select_from(Event)
            .join(instant, true())
            .where(Event.id == event_id, Event.status == "PUBLISHED")
        ).one_or_none()
        if row is None:
            raise _not_found()
        return Availability(
            event_id=row.id,
            capacity=row.capacity,
            available_seats=row.available_seats,
            as_of=row.as_of,
        )
