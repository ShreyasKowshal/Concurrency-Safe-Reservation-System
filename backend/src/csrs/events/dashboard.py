"""Owner-only, write-free booking snapshot. No customer identities are exposed."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select, true, tuple_
from sqlalchemy.orm import Session, aliased

from csrs.events.errors import EventError
from csrs.events.pagination import decode_cursor, encode_cursor
from csrs.events.schemas import Timestamp
from csrs.models import Event, Reservation, User
from csrs.reservations.schemas import ReservationResponse
from csrs.reservations.service import representation


class BookingCounts(BaseModel):
    valid_held: int
    overdue_held: int
    confirmed: int
    cancelled: int
    expired: int


class BookingDashboard(BaseModel):
    event_id: UUID
    capacity: int
    allocated_seats: int
    as_of: Timestamp
    counts: BookingCounts
    items: list[ReservationResponse]
    next_cursor: str | None


def dashboard(
    db: Session, user: User, event_id: UUID, limit: int, cursor: str | None
) -> BookingDashboard:
    scope = f"dashboard:{user.id}:{event_id}"
    position = decode_cursor(cursor, scope) if cursor is not None else None
    # One statement: counts, counter, page, and clock share one MVCC snapshot.
    instant = select(func.clock_timestamp().label("at")).cte("instant").prefix_with("MATERIALIZED")
    held = Reservation.status == "HELD"
    counts = (
        select(
            func.count()
            .filter(held & (Reservation.hold_expires_at > instant.c.at))
            .label("valid_held"),
            func.count()
            .filter(held & (Reservation.hold_expires_at <= instant.c.at))
            .label("overdue_held"),
            *[
                func.count().filter(Reservation.status == status.upper()).label(status)
                for status in ("confirmed", "cancelled", "expired")
            ],
        )
        .where(Reservation.event_id == Event.id)
        .correlate(Event, instant)
        .lateral("counts")
    )
    page = select(Reservation).where(Reservation.event_id == Event.id)
    if position is not None:
        page = page.where(tuple_(Reservation.created_at, Reservation.id) > tuple_(*position))
    page = (
        page.order_by(Reservation.created_at, Reservation.id)
        .limit(limit + 1)
        .correlate(Event)
        .lateral("page")
    )
    booking = aliased(Reservation, page)
    statement = (
        select(Event, instant.c.at, *counts.c, booking)
        .select_from(Event)
        .join(instant, true())
        .join(counts, true())
        .outerjoin(page, true())
        .where(Event.id == event_id, Event.organizer_id == user.id)
        .order_by(page.c.created_at, page.c.id)
    )
    with db.begin():
        results = db.execute(statement).all()
        if not results:
            raise EventError(404, "NOT_FOUND", "Resource not found.")
        first = results[0]
        event, now = first[0], first[1]
        rows = [row[-1] for row in results if row[-1] is not None]
        return BookingDashboard(
            event_id=event.id,
            capacity=event.capacity,
            allocated_seats=event.allocated_seats,
            as_of=now,
            counts=BookingCounts(
                **{key: first._mapping[key] for key in BookingCounts.model_fields}
            ),
            items=[representation(row, now) for row in rows[:limit]],
            next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id, scope)
            if len(rows) > limit
            else None,
        )
