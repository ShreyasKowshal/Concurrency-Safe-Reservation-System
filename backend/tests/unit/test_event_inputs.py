import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from csrs.events.errors import EventError
from csrs.events.pagination import decode_cursor, encode_cursor
from csrs.events.schemas import CapacityUpdate, EventCreate, EventPatch
from csrs.main import create_app


def event_body():
    return {
        "title": "  PostgreSQL workshop  ",
        "location": "  Room 101  ",
        "starts_at": "2035-01-02T15:00:00+05:30",
        "ends_at": "2035-01-02T17:00:00+05:30",
        "booking_closes_at": "2035-01-02T14:00:00+05:30",
        "capacity": 10,
    }


def test_event_input_normalizes_text_and_utc_and_defaults_description():
    event = EventCreate(**event_body())
    assert event.title == "PostgreSQL workshop" and event.location == "Room 101"
    assert event.description == ""
    assert event.starts_at == datetime(2035, 1, 2, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize("capacity", [0, -1, True, False, 1.5, "10", None, 2147483648])
def test_capacity_rejects_coercion_nonpositive_and_integer_overflow(capacity):
    with pytest.raises(ValidationError):
        CapacityUpdate(capacity=capacity)


@pytest.mark.parametrize("capacity", [1, 2147483647])
def test_capacity_accepts_postgres_integer_bounds(capacity):
    assert CapacityUpdate(capacity=capacity).capacity == capacity


@pytest.mark.parametrize(
    "change",
    [
        {"title": "  "},
        {"title": "x" * 201},
        {"location": "\t\n"},
        {"location": "x" * 301},
        {"description": "x" * 10001},
        {"starts_at": "2035-01-02T15:00:00"},
        {"starts_at": 2050000000},
        {"starts_at": "2050000000"},
        {"starts_at": "2035-01-02 15:00:00+05:30"},
        {"starts_at": "0001-01-01T00:00:00+05:30"},
        {"ends_at": "not-a-date"},
        {"ends_at": "2035-01-02T15:00:00+05:30"},
        {"booking_closes_at": "2035-01-02T16:00:00+05:30"},
        {"organizer_id": str(uuid4())},
        {"status": "PUBLISHED"},
        {"allocated_seats": 1},
        {"id": str(uuid4())},
    ],
)
def test_creation_rejects_invalid_fields_and_forged_state(change):
    with pytest.raises(ValidationError):
        EventCreate(**(event_body() | change))


@pytest.mark.parametrize(
    "change",
    [{}, {"capacity": 10}, {"organizer_id": str(uuid4())}, {"status": "CLOSED"}]
    + [{field: None} for field in EventPatch.model_fields],
)
def test_patch_rejects_empty_unknown_and_explicit_null_fields(change):
    with pytest.raises(ValidationError):
        EventPatch(**change)


def test_patch_tracks_only_supplied_fields_and_can_clear_description():
    body = EventPatch(description="")
    assert body.model_dump(exclude_unset=True) == {"description": ""}


def test_cursor_roundtrip_with_stable_scope_and_uuid():
    instant, identifier = datetime(2035, 1, 2, tzinfo=UTC), uuid4()
    assert decode_cursor(encode_cursor(instant, identifier, "public"), "public") == (
        instant,
        identifier,
    )


@pytest.mark.parametrize("cursor", ["", "*", "not base64", "a" * 513, "W10=", "bnVsbA=="])
def test_cursor_rejects_malformed_data(cursor):
    with pytest.raises(EventError) as error:
        decode_cursor(cursor, "public")
    assert error.value.code == "INVALID_CURSOR" and error.value.status == 422


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "organizer:someone-else"},
        {"v": True},
        {"v": 2},
        {"id": "not-a-uuid"},
        {"starts_at": "2035-01-02T00:00:00"},
        {"extra": "unrecognized"},
    ],
)
def test_cursor_rejects_wrong_scope_version_and_types(change):
    body = {"v": 1, "scope": "public", "starts_at": "2035-01-02T00:00:00Z", "id": str(uuid4())}
    cursor = base64.urlsafe_b64encode(json.dumps(body | change).encode()).decode()
    with pytest.raises(EventError):
        decode_cursor(cursor, "public")


def test_openapi_protects_organizer_operations_and_preserves_path_query_parameters(settings):
    document = create_app(settings).openapi()
    for path, operations in document["paths"].items():
        if path.startswith("/api/v1/organizer/events"):
            for method, operation in operations.items():
                expected = {"SessionCookie": []}
                if method != "get":
                    expected["CsrfToken"] = []
                    assert any(p["name"] == "Origin" for p in operation["parameters"])
                assert operation["security"] == [expected]
                if "{event_id}" in path:
                    assert any(p["name"] == "event_id" for p in operation["parameters"])
        if path.startswith("/api/v1/events"):
            assert "security" not in operations["get"]
    listing = document["paths"]["/api/v1/organizer/events"]["get"]
    assert {p["name"] for p in listing["parameters"]} == {"limit", "cursor"}

    # Explicit union responses must not reference schemas absent from the generated document.
    def check_refs(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert (
                    value["$ref"].removeprefix("#/components/schemas/")
                    in document["components"]["schemas"]
                )
            for child in value.values():
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)

    check_refs(document)
