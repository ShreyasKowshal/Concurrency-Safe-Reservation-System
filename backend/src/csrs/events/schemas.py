"""Explicit event inputs and public/private outputs; no client-owned state fields."""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


def timestamp_input(value):
    if not isinstance(value, str | datetime) or (
        isinstance(value, str)
        and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})",
            value,
        )
        is None
    ):
        raise ValueError("Use an RFC 3339 timestamp with a timezone")
    return value


def utc_timestamp(value: datetime) -> datetime:
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ValueError("Timestamp is outside the supported UTC range") from None


Timestamp = Annotated[
    AwareDatetime,
    BeforeValidator(timestamp_input),
    AfterValidator(utc_timestamp),
]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Location = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Description = Annotated[str, StringConstraints(max_length=10000)]
Capacity = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
EventStatus = Literal["DRAFT", "PUBLISHED", "CLOSED"]


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    title: Title
    description: Description = ""
    location: Location
    starts_at: Timestamp
    ends_at: Timestamp
    booking_closes_at: Timestamp
    capacity: Capacity

    @model_validator(mode="after")
    def schedule(self) -> Self:
        if not self.booking_closes_at <= self.starts_at < self.ends_at:
            raise ValueError("Require booking_closes_at <= starts_at < ends_at")
        return self


class EventPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    title: Title | None = None
    description: Description | None = None
    location: Location | None = None
    starts_at: Timestamp | None = None
    ends_at: Timestamp | None = None
    booking_closes_at: Timestamp | None = None

    @model_validator(mode="after")
    def nonempty_nonnull(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Supply at least one editable field")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Editable fields cannot be null")
        return self


class CapacityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    capacity: Capacity


class EventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    location: str
    starts_at: Timestamp
    booking_closes_at: Timestamp
    status: EventStatus
    capacity: int


class EventDetail(EventSummary):
    description: str
    ends_at: Timestamp
    organizer_id: UUID


class OrganizerEvent(EventDetail):
    allocated_seats: int


class OrganizerEventSummary(EventSummary):
    allocated_seats: int


class PublicEventPage(BaseModel):
    items: list[EventSummary]
    next_cursor: str | None


class OrganizerEventPage(BaseModel):
    items: list[OrganizerEventSummary]
    next_cursor: str | None
