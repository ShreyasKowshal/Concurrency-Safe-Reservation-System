"""Public event discovery and owner-only organizer commands."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from csrs.api.redis_dependencies import mutation_quota, public_quota
from csrs.auth.dependencies import Database, require_organizer
from csrs.auth.http import validate_mutation_request
from csrs.auth.schemas import EmptyRequest, ErrorResponse
from csrs.events import service
from csrs.events.schemas import (
    CapacityUpdate,
    EventCreate,
    EventDetail,
    EventPatch,
    OrganizerEvent,
    OrganizerEventPage,
    PublicEventPage,
)
from csrs.models import User

validation_errors = {
    "description": "Invalid request fields, combined schedule, or pagination cursor.",
    "content": {
        "application/json": {
            "schema": {
                "anyOf": [
                    {"$ref": "#/components/schemas/HTTPValidationError"},
                    {"$ref": "#/components/schemas/ErrorResponse"},
                ]
            }
        }
    },
}
public_router = APIRouter(
    prefix="/events",
    tags=["public events"],
    responses={
        404: {"model": ErrorResponse},
        422: validation_errors,
        503: {"model": ErrorResponse},
    },
)
organizer_router = APIRouter(
    prefix="/organizer/events",
    tags=["organizer events"],
    responses={
        **{code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 415, 503)},
        422: validation_errors,
    },
)
Organizer = Annotated[User, Depends(require_organizer)]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(min_length=1, max_length=512)]
mutation = [Depends(validate_mutation_request)]


def _credentials(request: Request) -> tuple[str | None, str | None]:
    return (
        request.cookies.get(request.app.state.settings.session_cookie_name),
        request.headers.get("x-csrf-token"),
    )


@public_router.get("", response_model=PublicEventPage)
def public_events(
    request: Request, db: Database, limit: Limit = 20, cursor: Cursor = None
) -> PublicEventPage:
    """Published events only, ordered by starts_at and id. No booking guarantee."""
    public_quota(request)
    return service.list_public_events(db, limit, cursor)


@public_router.get("/{event_id}", response_model=EventDetail)
def public_event(event_id: UUID, db: Database, request: Request) -> EventDetail:
    """Public metadata may be cached for the configured TTL (default 15s, maximum 60s).

    Every hit checks current PostgreSQL publication visibility. Availability is never cached.
    """
    public_quota(request)
    support = request.app.state.redis_support
    if not request.app.state.settings.metadata_cache_enabled:
        return service.get_public_event(db, event_id)
    service.require_public_event(db, event_id)
    cached, ticket = support.lookup(event_id)
    if cached is not None:
        return cached
    result = service.get_public_event(db, event_id)
    support.fill(ticket, result)
    return result


@organizer_router.get("", response_model=OrganizerEventPage)
def own_events(
    db: Database, user: Organizer, limit: Limit = 20, cursor: Cursor = None
) -> OrganizerEventPage:
    """Only the authenticated organizer's events, including drafts and closed events."""
    return service.list_owned_events(db, user, limit, cursor)


@organizer_router.get("/{event_id}", response_model=OrganizerEvent)
def own_event(event_id: UUID, db: Database, user: Organizer) -> OrganizerEvent:
    return service.get_owned_event(db, event_id, user)


@organizer_router.post("", status_code=201, response_model=OrganizerEvent, dependencies=mutation)
def create(body: EventCreate, request: Request, db: Database) -> OrganizerEvent:
    mutation_quota(request, db, organizer=True)
    return service.create_event(db, *_credentials(request), body)


@organizer_router.patch("/{event_id}", response_model=OrganizerEvent, dependencies=mutation)
def edit(event_id: UUID, body: EventPatch, request: Request, db: Database) -> OrganizerEvent:
    mutation_quota(request, db, organizer=True)
    result = service.edit_event(db, *_credentials(request), event_id, body)
    request.app.state.redis_support.invalidate(event_id)
    return result


@organizer_router.patch(
    "/{event_id}/capacity", response_model=OrganizerEvent, dependencies=mutation
)
def capacity(
    event_id: UUID, body: CapacityUpdate, request: Request, db: Database
) -> OrganizerEvent:
    mutation_quota(request, db, organizer=True)
    result = service.change_capacity(db, *_credentials(request), event_id, body.capacity)
    request.app.state.redis_support.invalidate(event_id)
    return result


@organizer_router.post("/{event_id}/publish", response_model=OrganizerEvent, dependencies=mutation)
def publish(event_id: UUID, body: EmptyRequest, request: Request, db: Database) -> OrganizerEvent:
    mutation_quota(request, db, organizer=True)
    result = service.publish_event(db, *_credentials(request), event_id)
    request.app.state.redis_support.invalidate(event_id)
    return result


@organizer_router.post("/{event_id}/close", response_model=OrganizerEvent, dependencies=mutation)
def close(event_id: UUID, body: EmptyRequest, request: Request, db: Database) -> OrganizerEvent:
    mutation_quota(request, db, organizer=True)
    result = service.close_event(db, *_credentials(request), event_id)
    request.app.state.redis_support.invalidate(event_id)
    return result
