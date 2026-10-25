from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from csrs.events.schemas import Timestamp


class ReservationResponse(BaseModel):
    id: UUID
    event_id: UUID
    status: Literal["HELD", "CONFIRMED", "CANCELLED", "EXPIRED"]
    created_at: Timestamp
    hold_expires_at: Timestamp
    confirmed_at: Timestamp | None
    cancelled_at: Timestamp | None
    expired_at: Timestamp | None
    server_time: Timestamp


class ReservationPage(BaseModel):
    items: list[ReservationResponse]
    next_cursor: str | None


class Availability(BaseModel):
    event_id: UUID
    capacity: int
    available_seats: int
    as_of: Timestamp
