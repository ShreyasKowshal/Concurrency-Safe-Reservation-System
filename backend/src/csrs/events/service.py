"""Explicit event transactions. All existing-event writes take the event lock first.

Capacity edits share reservation expiration under this same event lock.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from csrs.auth.dependencies import require_organizer, require_owner
from csrs.auth.errors import authentication_required
from csrs.auth.service import database_time, require_session
from csrs.events.errors import EventError
from csrs.events.pagination import decode_cursor, encode_cursor
from csrs.events.schemas import (
    EventCreate,
    EventDetail,
    EventPatch,
    EventSummary,
    OrganizerEvent,
    OrganizerEventPage,
    OrganizerEventSummary,
    PublicEventPage,
)
from csrs.models import Event, SessionKind, User
from csrs.reservations.transitions import expire_due_holds


def _organizer(db: Session, cookie: str | None, csrf: str | None) -> User:
    record = require_session(db, cookie, csrf, SessionKind.AUTHENTICATED)
    user = db.get(User, record.user_id, populate_existing=True)
    if user is None or not user.is_active:
        raise authentication_required()
    return require_organizer(user)


def _not_found() -> EventError:
    return EventError(404, "NOT_FOUND", "Resource not found.")


def _invalid_state() -> EventError:
    return EventError(
        409, "INVALID_EVENT_STATE", "This operation is not allowed in this event state."
    )


@contextmanager
def _owned_event(
    db: Session, cookie: str | None, csrf: str | None, event_id: UUID
) -> Iterator[Event]:
    with db.begin():
        actor = _organizer(db, cookie, csrf)
        event = db.scalar(
            select(Event)
            .where(Event.id == event_id, Event.organizer_id == actor.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if event is None:
            raise _not_found()
        # A lock wait can outlive a session or an authorization change. Read again.
        actor = _organizer(db, cookie, csrf)
        require_owner(event.organizer_id, actor)
        yield event


def create_event(
    db: Session, cookie: str | None, csrf: str | None, body: EventCreate
) -> OrganizerEvent:
    with db.begin():
        actor = _organizer(db, cookie, csrf)
        event = Event(organizer_id=actor.id, **body.model_dump())
        db.add(event)
        db.flush()
        result = OrganizerEvent.model_validate(event)
    return result


def edit_event(
    db: Session, cookie: str | None, csrf: str | None, event_id: UUID, body: EventPatch
) -> OrganizerEvent:
    with _owned_event(db, cookie, csrf, event_id) as event:
        if event.status == "CLOSED":
            raise _invalid_state()
        changes = body.model_dump(exclude_unset=True)
        if event.status == "PUBLISHED" and {"starts_at", "booking_closes_at"} & changes.keys():
            raise EventError(
                409,
                "EVENT_SCHEDULE_IMMUTABLE",
                "Published start and booking deadline cannot change.",
            )
        for name, value in changes.items():
            setattr(event, name, value)
        if not event.booking_closes_at <= event.starts_at < event.ends_at:
            raise EventError(
                422, "INVALID_EVENT_SCHEDULE", "Require booking_closes_at <= starts_at < ends_at."
            )
        db.flush()
        result = OrganizerEvent.model_validate(event)
    return result


def change_capacity(
    db: Session, cookie: str | None, csrf: str | None, event_id: UUID, capacity: int
) -> OrganizerEvent:
    error = None
    with _owned_event(db, cookie, csrf, event_id) as event:
        if event.status == "CLOSED":
            raise _invalid_state()
        expire_due_holds(db, event, database_time(db))
        if capacity < event.allocated_seats:
            error = EventError(
                409, "CAPACITY_BELOW_ALLOCATED", "Capacity cannot be below allocated seats."
            )
        else:
            event.capacity = capacity
        db.flush()
        result = OrganizerEvent.model_validate(event)
    if error is not None:
        raise error
    return result


def publish_event(
    db: Session, cookie: str | None, csrf: str | None, event_id: UUID
) -> OrganizerEvent:
    with _owned_event(db, cookie, csrf, event_id) as event:
        if event.status != "DRAFT":
            raise _invalid_state()
        now = database_time(db)
        if event.starts_at <= now or event.booking_closes_at <= now:
            raise EventError(
                409,
                "EVENT_NOT_PUBLISHABLE",
                "Publishing requires a future start and booking deadline.",
            )
        event.status = "PUBLISHED"
        db.flush()
        result = OrganizerEvent.model_validate(event)
    return result


def close_event(
    db: Session, cookie: str | None, csrf: str | None, event_id: UUID
) -> OrganizerEvent:
    with _owned_event(db, cookie, csrf, event_id) as event:
        if event.status != "PUBLISHED":
            raise _invalid_state()
        event.status = "CLOSED"
        db.flush()
        result = OrganizerEvent.model_validate(event)
    return result


def get_public_event(db: Session, event_id: UUID) -> EventDetail:
    with db.begin():
        event = db.scalar(select(Event).where(Event.id == event_id, Event.status == "PUBLISHED"))
        if event is None:
            raise _not_found()
        return EventDetail.model_validate(event)


def get_owned_event(db: Session, event_id: UUID, user: User) -> OrganizerEvent:
    with db.begin():
        event = db.get(Event, event_id)
        if event is None:
            raise _not_found()
        require_owner(event.organizer_id, user)
        return OrganizerEvent.model_validate(event)


def _page(db: Session, limit: int, cursor: str | None, organizer_id: UUID | None):
    scope = "public" if organizer_id is None else f"organizer:{organizer_id}"
    statement = select(Event).where(
        Event.status == "PUBLISHED" if organizer_id is None else Event.organizer_id == organizer_id
    )
    if cursor is not None:
        instant, event_id = decode_cursor(cursor, scope)
        statement = statement.where(tuple_(Event.starts_at, Event.id) > tuple_(instant, event_id))
    rows = list(db.scalars(statement.order_by(Event.starts_at, Event.id).limit(limit + 1)))
    next_cursor = (
        encode_cursor(rows[limit - 1].starts_at, rows[limit - 1].id, scope)
        if len(rows) > limit
        else None
    )
    return rows[:limit], next_cursor


def list_public_events(db: Session, limit: int, cursor: str | None) -> PublicEventPage:
    with db.begin():
        rows, next_cursor = _page(db, limit, cursor, organizer_id=None)
        return PublicEventPage(
            items=[EventSummary.model_validate(row) for row in rows], next_cursor=next_cursor
        )


def list_owned_events(
    db: Session, user: User, limit: int, cursor: str | None
) -> OrganizerEventPage:
    with db.begin():
        rows, next_cursor = _page(db, limit, cursor, organizer_id=user.id)
        return OrganizerEventPage(
            items=[OrganizerEventSummary.model_validate(row) for row in rows],
            next_cursor=next_cursor,
        )
