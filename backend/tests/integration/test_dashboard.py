"""Real PostgreSQL tests for the narrow organizer booking snapshot."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from csrs.models import Event, Reservation, Role
from csrs.reservations.service import database_time

pytestmark = pytest.mark.integration
BASE = "/api/v1/organizer/events"


@pytest.mark.parametrize("status", ["DRAFT", "PUBLISHED", "CLOSED"])
def test_empty_dashboard_and_visibility(client, user_factory, event_factory, login_headers, status):
    owner = user_factory("owner@example.com", role=Role.ORGANIZER)
    event = event_factory(owner, status=status)
    url = f"{BASE}/{event.id}/dashboard"
    assert client.get(url).status_code == 401
    attendee = user_factory()
    login_headers(client, attendee.normalized_email)
    assert client.get(url).status_code == 403
    client.cookies.clear()
    other = user_factory("other@example.com", role=Role.ORGANIZER)
    login_headers(client, other.normalized_email)
    assert client.get(url).status_code == 404
    client.cookies.clear()
    login_headers(client, owner.normalized_email)
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["items"] == [] and body["next_cursor"] is None
    assert body["counts"] == dict(valid_held=0, overdue_held=0, confirmed=0, cancelled=0, expired=0)
    assert body["allocated_seats"] == 0 and body["capacity"] == 10
    assert "email" not in response.text and "user_id" not in response.text


def test_dashboard_counts_effective_status_and_write_free_snapshot(
    client, booking, clean_engine, user_factory, login_headers
):
    event, owner = booking["event"], booking["owner"]
    with Session(clean_engine) as db, db.begin():
        now = database_time(db)
        for index, state in enumerate(["HELD", "HELD", "CONFIRMED", "CANCELLED", "EXPIRED"]):
            user = user_factory(f"row{index}@example.com")
            created = now - timedelta(minutes=10)
            expires = now + timedelta(minutes=3) if index == 0 else now - timedelta(minutes=5)
            db.add(
                Reservation(
                    event_id=event.id,
                    user_id=user.id,
                    status=state,
                    created_at=created,
                    hold_expires_at=expires,
                    confirmed_at=created + timedelta(seconds=1) if state == "CONFIRMED" else None,
                    cancelled_at=created + timedelta(seconds=1) if state == "CANCELLED" else None,
                    expired_at=expires if state == "EXPIRED" else None,
                )
            )
        db.get(Event, event.id).allocated_seats = 3
    login_headers(client, owner.normalized_email)
    body = client.get(f"{BASE}/{event.id}/dashboard").json()
    assert body["counts"] == dict(valid_held=1, overdue_held=1, confirmed=1, cancelled=1, expired=1)
    assert body["allocated_seats"] == 3
    assert sorted(row["status"] for row in body["items"]) == [
        "CANCELLED",
        "CONFIRMED",
        "EXPIRED",
        "EXPIRED",
        "HELD",
    ]
    assert all(row["server_time"] == body["as_of"] for row in body["items"])
    with Session(clean_engine) as db:
        assert len(list(db.scalars(select(Reservation).where(Reservation.status == "HELD")))) == 2
        assert db.get(Event, event.id).allocated_seats == 3


def test_dashboard_keyset_scope_and_invalid_pagination(
    client, booking, event_factory, login_headers
):
    booking["execute"]()
    # A second reservation is made by another real user/session.
    other = booking["owner"]
    booking["execute"](actor_session=booking["credentials"](other))
    login_headers(client, other.normalized_email)
    url = f"{BASE}/{booking['event'].id}/dashboard"
    first = client.get(url, params={"limit": 1}).json()
    second = client.get(url, params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert second["next_cursor"] is None
    hidden = event_factory(other)
    assert (
        client.get(
            f"{BASE}/{hidden.id}/dashboard", params={"cursor": first["next_cursor"]}
        ).status_code
        == 422
    )
    for params in ({"limit": 0}, {"limit": 101}, {"cursor": "invalid"}):
        assert client.get(url, params=params).status_code == 422
