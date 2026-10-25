"""Booking transport; services own durable outcomes and transaction boundaries."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from csrs.api.events import Cursor, Limit, _credentials, validation_errors
from csrs.auth.dependencies import CurrentUser, Database
from csrs.auth.http import validate_mutation_request
from csrs.auth.schemas import EmptyRequest, ErrorResponse
from csrs.reservations import service
from csrs.reservations.schemas import Availability, ReservationPage, ReservationResponse

router = APIRouter(
    tags=["reservations"],
    responses={
        **{code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 415, 503)},
        422: validation_errors
        | {"description": "Invalid fields, idempotency key, or history cursor."},
    },
)
Key = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[!-~]+$")
]


def validate_command(request: Request) -> None:
    validate_mutation_request(request)
    if len(request.headers.getlist("idempotency-key")) > 1:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("header", "Idempotency-Key"),
                    "msg": "Supply exactly one Idempotency-Key.",
                }
            ]
        )


mutation = [Depends(validate_command)]
replay_headers = {
    "Idempotency-Replayed": {
        "description": "Whether this is the original stored outcome.",
        "schema": {"type": "string", "enum": ["true", "false"]},
    }
}


def _command(
    request: Request, db: Database, resource_id: UUID, action: str, key: str
) -> JSONResponse:
    reply = service.command(
        db,
        *_credentials(request),
        resource_id,
        action,
        key,
        ttl_seconds=request.app.state.settings.hold_ttl_seconds,
    )
    return JSONResponse(
        status_code=reply.status,
        content=reply.body,
        headers={
            "Idempotency-Replayed": str(reply.replayed).lower(),
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/events/{event_id}/holds",
    status_code=201,
    response_model=ReservationResponse,
    dependencies=mutation,
    responses={
        201: {"headers": replay_headers},
        409: {"model": ErrorResponse, "headers": replay_headers},
    },
)
def hold(event_id: UUID, body: EmptyRequest, request: Request, db: Database, idempotency_key: Key):
    return _command(request, db, event_id, "hold", idempotency_key)


@router.post(
    "/reservations/{reservation_id}/confirm",
    response_model=ReservationResponse,
    dependencies=mutation,
    responses={
        200: {"headers": replay_headers},
        409: {"model": ErrorResponse, "headers": replay_headers},
    },
)
def confirm(
    reservation_id: UUID, body: EmptyRequest, request: Request, db: Database, idempotency_key: Key
):
    return _command(request, db, reservation_id, "confirm", idempotency_key)


@router.post(
    "/reservations/{reservation_id}/cancel",
    response_model=ReservationResponse,
    dependencies=mutation,
    responses={
        200: {"headers": replay_headers},
        409: {"model": ErrorResponse, "headers": replay_headers},
    },
)
def cancel(
    reservation_id: UUID, body: EmptyRequest, request: Request, db: Database, idempotency_key: Key
):
    return _command(request, db, reservation_id, "cancel", idempotency_key)


@router.get("/reservations/{reservation_id}", response_model=ReservationResponse)
def detail(reservation_id: UUID, db: Database, user: CurrentUser):
    return service.get_reservation(db, reservation_id, user)


@router.get("/me/reservations", response_model=ReservationPage)
def history(db: Database, user: CurrentUser, limit: Limit = 20, cursor: Cursor = None):
    return service.list_reservations(db, user, limit, cursor)


@router.get("/events/{event_id}/availability", response_model=Availability)
def availability(event_id: UUID, db: Database):
    return service.availability(db, event_id)
