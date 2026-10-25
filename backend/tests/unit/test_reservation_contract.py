import pytest
from pydantic import ValidationError

from csrs.config import Settings
from csrs.main import create_app
from csrs.reservations.service import fingerprint


def test_fingerprint_is_stable_and_scoped_to_canonical_path():
    hold = "/api/v1/events/00000000-0000-0000-0000-000000000001/holds"
    assert len(fingerprint(hold)) == 64
    assert fingerprint(hold) == fingerprint(hold)
    assert fingerprint(hold) != fingerprint(hold.replace("000001", "000002"))
    assert fingerprint("/api/v1/reservations/id/confirm") != fingerprint(
        "/api/v1/reservations/id/cancel"
    )


@pytest.mark.parametrize("ttl", [0, -1, 3601])
def test_hold_ttl_rejects_out_of_bounds(settings, ttl):
    with pytest.raises(ValidationError):
        Settings(**(settings.model_dump() | {"hold_ttl_seconds": ttl}))


def test_default_hold_ttl_is_five_minutes(settings):
    assert settings.hold_ttl_seconds == 300


def test_reservation_output_normalizes_database_timezone_to_utc():
    from uuid import uuid4

    from csrs.reservations.schemas import ReservationResponse

    row = ReservationResponse(
        id=uuid4(),
        event_id=uuid4(),
        status="HELD",
        created_at="2035-01-01T12:00:00+05:30",
        hold_expires_at="2035-01-01T12:05:00+05:30",
        confirmed_at=None,
        cancelled_at=None,
        expired_at=None,
        server_time="2035-01-01T12:00:00+05:30",
    )
    assert row.model_dump(mode="json")["created_at"] == "2035-01-01T06:30:00Z"


def test_reservation_openapi_security_keys_responses_and_public_availability(settings):
    document = create_app(settings).openapi()
    for path, operations in document["paths"].items():
        if path.endswith(("/holds", "/confirm", "/cancel")):
            operation = operations["post"]
            assert operation["security"] == [{"SessionCookie": [], "CsrfToken": []}]
            key = next(p for p in operation["parameters"] if p["name"] == "Idempotency-Key")
            assert key["required"] and key["schema"]["maxLength"] == 128
            assert key["schema"]["minLength"] == 1
            assert any(p["in"] == "path" for p in operation["parameters"])
            success = "201" if path.endswith("/holds") else "200"
            assert "Idempotency-Replayed" in operation["responses"][success]["headers"]
        elif path.startswith(("/api/v1/reservations/", "/api/v1/me/reservations")):
            assert operations["get"]["security"] == [{"SessionCookie": []}]
        elif path.endswith("/availability"):
            assert "security" not in operations["get"]
