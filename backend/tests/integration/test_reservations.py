"""Reservation HTTP behavior and committed state, using only real PostgreSQL."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from csrs.auth.service import database_time
from csrs.models import Event, IdempotencyRecord, Reservation
from csrs.reservations import service

pytestmark = pytest.mark.integration


def assert_consistent(engine):
    # One MVCC statement: never compare observations from different committed states.
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("""
            SELECT count(*) FROM events e WHERE allocated_seats < 0
            OR allocated_seats > capacity OR allocated_seats != (
                SELECT count(*) FROM reservations r WHERE r.event_id=e.id
                AND r.status IN ('HELD','CONFIRMED'))
        """)
            )
            == 0
        )
        assert (
            connection.scalar(
                text("""
            SELECT count(*) FROM (SELECT user_id,event_id FROM reservations
            WHERE status IN ('HELD','CONFIRMED') GROUP BY user_id,event_id
            HAVING count(*) > 1) duplicates
        """)
            )
            == 0
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.completed_at.is_(None))
            )
            == 0
        )


def headers(booking, key="request-key", actor=None):
    actor = actor or booking["session"]
    return {
        "Cookie": f"csrs_session={actor.cookie}",
        "X-CSRF-Token": actor.csrf_token,
        "Origin": "http://localhost:5173",
        "Idempotency-Key": key,
    }


def seed_reservation(engine, booking, status="HELD", due=False):
    with Session(engine, expire_on_commit=False) as db, db.begin():
        now = database_time(db)
        row = Reservation(
            event_id=booking["event"].id,
            user_id=booking["user"].id,
            status=status,
            created_at=now - timedelta(minutes=10),
            hold_expires_at=now + timedelta(minutes=-1 if due else 4),
        )
        if status == "CONFIRMED":
            row.confirmed_at = now - timedelta(minutes=5)
        elif status == "CANCELLED":
            row.cancelled_at = now
        elif status == "EXPIRED":
            row.hold_expires_at = now - timedelta(minutes=1)
            row.expired_at = now
        db.add(row)
        db.get(Event, booking["event"].id).allocated_seats = int(status in {"HELD", "CONFIRMED"})
        db.flush()
        return row


def test_http_lifecycle_and_original_response_replay(client, booking, clean_engine):
    event = booking["event"]
    hold = client.post(f"/api/v1/events/{event.id}/holds", json={}, headers=headers(booking))
    assert hold.status_code == 201
    assert hold.headers["idempotency-replayed"] == "false"
    held = hold.json()
    assert set(held) == {
        "id",
        "event_id",
        "status",
        "created_at",
        "hold_expires_at",
        "confirmed_at",
        "cancelled_at",
        "expired_at",
        "server_time",
    }
    assert held["status"] == "HELD"
    reservation_id = held["id"]
    confirm = client.post(
        f"/api/v1/reservations/{reservation_id}/confirm",
        json={},
        headers=headers(booking, "confirm"),
    )
    assert confirm.status_code == 200 and confirm.json()["status"] == "CONFIRMED"
    # Lost hold response is recovered exactly, even though the resource has since changed.
    replay = client.post(f"/api/v1/events/{event.id}/holds", json={}, headers=headers(booking))
    assert replay.status_code == 201 and replay.json() == held
    assert replay.headers["idempotency-replayed"] == "true"
    assert (
        client.get(f"/api/v1/reservations/{reservation_id}", headers=headers(booking)).json()[
            "status"
        ]
        == "CONFIRMED"
    )
    cancelled = client.post(
        f"/api/v1/reservations/{reservation_id}/cancel", json={}, headers=headers(booking, "cancel")
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["confirmed_at"] == confirm.json()["confirmed_at"]
    rebook = booking["execute"]()
    assert rebook.status == 201 and rebook.body["id"] != reservation_id
    assert_consistent(clean_engine)


@pytest.mark.parametrize(
    "status,action,expected,code",
    [
        ("HELD", "confirm", "CONFIRMED", None),
        ("HELD", "cancel", "CANCELLED", None),
        ("CONFIRMED", "confirm", "CONFIRMED", None),
        ("CONFIRMED", "cancel", "CANCELLED", None),
        ("CANCELLED", "cancel", "CANCELLED", None),
        ("EXPIRED", "cancel", "EXPIRED", None),
        ("CANCELLED", "confirm", "CANCELLED", "INVALID_RESERVATION_STATE"),
        ("EXPIRED", "confirm", "EXPIRED", "HOLD_EXPIRED"),
    ],
)
def test_state_table_and_duplicate_commands(booking, clean_engine, status, action, expected, code):
    row = seed_reservation(clean_engine, booking, status)
    result = booking["execute"](action, row.id, "transition")
    assert result.status == (409 if code else 200)
    assert (result.body["error"]["code"] if code else result.body["status"]) == (code or expected)
    replay = booking["execute"](action, row.id, "transition")
    assert replay.replayed and replay.body == result.body
    again = booking["execute"](action, row.id)
    assert again.status == result.status
    with Session(clean_engine) as db:
        assert db.get(Reservation, row.id).status == expected
    assert_consistent(clean_engine)


@pytest.mark.parametrize("offset", [-1, 0, 1])
@pytest.mark.parametrize("action", ["confirm", "cancel"])
def test_exact_hold_deadline(booking, clean_engine, monkeypatch, offset, action):
    row = seed_reservation(clean_engine, booking)
    decision = row.hold_expires_at + timedelta(microseconds=offset)
    monkeypatch.setattr(service, "database_time", lambda db: decision)
    result = booking["execute"](action, row.id)
    expected = "EXPIRED" if offset >= 0 else "CONFIRMED" if action == "confirm" else "CANCELLED"
    assert result.status == (409 if offset >= 0 and action == "confirm" else 200)
    with Session(clean_engine) as db:
        stored = db.get(Reservation, row.id)
        assert stored.status == expected
        assert (
            stored.expired_at
            if offset >= 0
            else stored.confirmed_at
            if action == "confirm"
            else stored.cancelled_at
        ) == decision
    assert_consistent(clean_engine)


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_confirmed_cancellation_start_boundary(booking, clean_engine, monkeypatch, offset):
    row = seed_reservation(clean_engine, booking, "CONFIRMED", due=True)
    monkeypatch.setattr(
        service,
        "database_time",
        lambda db: booking["event"].starts_at + timedelta(microseconds=offset),
    )
    result = booking["execute"]("cancel", row.id)
    assert result.status == (200 if offset < 0 else 409)
    if offset >= 0:
        assert result.body["error"]["code"] == "CANCELLATION_CLOSED"
    assert_consistent(clean_engine)


def test_confirmed_never_expires_and_closed_event_allows_confirmation(booking, clean_engine):
    row = seed_reservation(clean_engine, booking)
    with Session(clean_engine) as db, db.begin():
        db.get(Event, booking["event"].id).status = "CLOSED"
    assert booking["execute"]().body["error"]["code"] == "BOOKING_CLOSED"
    assert booking["execute"]("confirm", row.id).status == 200
    with Session(clean_engine) as db, db.begin():
        stored = db.get(Reservation, row.id)
        stored.hold_expires_at = database_time(db) - timedelta(minutes=1)
        stored.confirmed_at = stored.hold_expires_at - timedelta(seconds=1)
    assert booking["execute"]("confirm", row.id).body["status"] == "CONFIRMED"
    assert_consistent(clean_engine)


@pytest.mark.parametrize(
    "ttl,remaining,expected", [(300, 86400, 300), (300, 100, 100), (30, 86400, 30)]
)
def test_ttl_capped_by_booking_deadline(
    booking, clean_engine, monkeypatch, ttl, remaining, expected
):
    with Session(clean_engine) as db:
        now = database_time(db) + timedelta(seconds=10)
    with Session(clean_engine) as db, db.begin():
        db.get(Event, booking["event"].id).booking_closes_at = now + timedelta(seconds=remaining)
    monkeypatch.setattr(service, "database_time", lambda db: now)
    with Session(clean_engine) as db:
        result = service.command(
            db,
            booking["session"].cookie,
            booking["session"].csrf_token,
            booking["event"].id,
            "hold",
            "ttl",
            ttl,
        )
    from datetime import datetime

    assert datetime.fromisoformat(result.body["hold_expires_at"]) - datetime.fromisoformat(
        result.body["created_at"]
    ) == timedelta(seconds=expected)


@pytest.mark.parametrize("offset", [0, 1])
def test_booking_deadline_rejects_zero_validity(booking, clean_engine, monkeypatch, offset):
    monkeypatch.setattr(
        service,
        "database_time",
        lambda db: booking["event"].booking_closes_at + timedelta(microseconds=offset),
    )
    assert booking["execute"]().body["error"]["code"] == "BOOKING_CLOSED"
    assert_consistent(clean_engine)


def test_request_cleanup_rebooking_effective_reads_and_capacity_edit(client, booking, clean_engine):
    row = seed_reservation(clean_engine, booking, due=True)
    event_id = booking["event"].id
    reply = client.get(f"/api/v1/reservations/{row.id}", headers=headers(booking))
    assert reply.json()["status"] == "EXPIRED" and reply.json()["expired_at"] is None
    availability = client.get(f"/api/v1/events/{event_id}/availability")
    assert availability.status_code == 200 and availability.json()["available_seats"] == 10
    with Session(clean_engine) as db:
        assert db.get(Reservation, row.id).status == "HELD"
        assert db.get(Event, event_id).allocated_seats == 1
    assert booking["execute"]().status == 201
    with Session(clean_engine) as db:
        assert db.get(Reservation, row.id).status == "EXPIRED"
    assert client.get(f"/api/v1/events/{event_id}/availability").json()["available_seats"] == 9
    # Make the replacement due, then reclaim it through the organizer capacity path.
    with Session(clean_engine) as db, db.begin():
        live = db.scalar(select(Reservation).where(Reservation.status == "HELD"))
        live.created_at = database_time(db) - timedelta(minutes=10)
        live.hold_expires_at = database_time(db) - timedelta(minutes=1)
    capacity = client.patch(
        f"/api/v1/organizer/events/{event_id}/capacity",
        json={"capacity": 1},
        headers=headers(booking, actor=booking["owner_session"]),
    )
    assert capacity.status_code == 200 and capacity.json()["allocated_seats"] == 0
    assert_consistent(clean_engine)


def test_stored_business_conflict_needs_new_key(booking, clean_engine, user_factory):
    with Session(clean_engine) as db, db.begin():
        db.get(Event, booking["event"].id).capacity = 1
    held = booking["execute"]()
    other = booking["credentials"](user_factory("other@example.com"))
    failed = booking["execute"](key="full", actor_session=other)
    assert failed.body["error"]["code"] == "EVENT_FULL"
    booking["execute"]("cancel", UUID(held.body["id"]))
    replay = booking["execute"](key="full", actor_session=other)
    assert replay.replayed and replay.body == failed.body
    assert booking["execute"](actor_session=other).status == 201
    assert_consistent(clean_engine)


def test_key_scope_mismatch_does_not_replace_original(booking, clean_engine, event_factory):
    original = booking["execute"](key="shared")
    another = event_factory(booking["owner"], status="PUBLISHED")
    for action, resource in [("hold", another.id), ("cancel", UUID(original.body["id"]))]:
        conflict = booking["execute"](action, resource, "shared")
        assert conflict.body["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert booking["execute"](key="shared").body == original.body
    assert_consistent(clean_engine)


@pytest.mark.parametrize("action", ["hold", "confirm", "cancel", "detail", "history"])
def test_missing_authentication(client, booking, clean_engine, action):
    held = booking["execute"]()
    resource = held.body["id"]
    path = (
        f"/api/v1/events/{booking['event'].id}/holds"
        if action == "hold"
        else f"/api/v1/reservations/{resource}/{action}"
    )
    if action == "detail":
        path = f"/api/v1/reservations/{resource}"
    if action == "history":
        path = "/api/v1/me/reservations"
    reply = (
        client.get(path)
        if action in {"detail", "history"}
        else client.post(
            path,
            json={},
            headers={"Origin": "http://localhost:5173", "Idempotency-Key": "unauthorized"},
        )
    )
    assert reply.status_code == 401 and reply.headers["cache-control"] == "no-store"
    assert_consistent(clean_engine)


@pytest.mark.parametrize("action", ["confirm", "cancel", "detail"])
def test_other_users_cannot_access_or_replay(client, booking, clean_engine, user_factory, action):
    held = booking["execute"](key="original")
    stranger = booking["credentials"](user_factory("stranger@example.com"))
    path = f"/api/v1/reservations/{held.body['id']}" + ("" if action == "detail" else f"/{action}")
    reply = (
        client.get(path, headers=headers(booking, actor=stranger))
        if action == "detail"
        else client.post(path, json={}, headers=headers(booking, "original", stranger))
    )
    assert reply.status_code == 404
    assert_consistent(clean_engine)


@pytest.mark.parametrize(
    "bad",
    ["csrf", "origin", "media", "body", "missing-key", "space-key", "long-key", "duplicate-key"],
)
def test_http_mutation_validation_is_not_recorded(client, booking, clean_engine, bad):
    request_headers = headers(booking)
    body = {}
    if bad == "csrf":
        request_headers["X-CSRF-Token"] = "0" * 64
    if bad == "origin":
        request_headers["Origin"] = "https://hostile.example"
    if bad == "media":
        request_headers["Content-Type"] = "text/plain"
    if bad == "body":
        body = {"user_id": str(booking["owner"].id)}
    if bad == "missing-key":
        del request_headers["Idempotency-Key"]
    if bad == "space-key":
        request_headers["Idempotency-Key"] = "has space"
    if bad == "long-key":
        request_headers["Idempotency-Key"] = "x" * 129
    if bad == "duplicate-key":
        request_headers = [*request_headers.items(), ("Idempotency-Key", "second")]
    reply = client.post(
        f"/api/v1/events/{booking['event'].id}/holds", json=body, headers=request_headers
    )
    assert reply.status_code == (
        403 if bad in {"csrf", "origin"} else 415 if bad == "media" else 422
    )
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
    assert_consistent(clean_engine)


def test_replay_still_requires_csrf_and_active_session(client, booking, clean_engine):
    booking["execute"](key="replay")
    request_headers = headers(booking, "replay")
    request_headers["X-CSRF-Token"] = "0" * 64
    assert (
        client.post(
            f"/api/v1/events/{booking['event'].id}/holds", json={}, headers=request_headers
        ).status_code
        == 403
    )
    with Session(clean_engine) as db, db.begin():
        db.execute(text("UPDATE sessions SET revoked_at=clock_timestamp()"))
    assert (
        client.post(
            f"/api/v1/events/{booking['event'].id}/holds",
            json={},
            headers=headers(booking, "replay"),
        ).status_code
        == 401
    )
    assert_consistent(clean_engine)


def test_private_history_pagination_and_cursor_scope(client, booking, clean_engine, user_factory):
    ids = []
    for _ in range(3):
        held = booking["execute"]()
        ids.append(held.body["id"])
        booking["execute"]("cancel", UUID(held.body["id"]))
    page = client.get("/api/v1/me/reservations?limit=2", headers=headers(booking)).json()
    assert [row["id"] for row in page["items"]] == ids[:2]
    tail = client.get(
        "/api/v1/me/reservations",
        params={"limit": 2, "cursor": page["next_cursor"]},
        headers=headers(booking),
    ).json()
    assert [row["id"] for row in tail["items"]] == ids[2:] and tail["next_cursor"] is None
    stranger = booking["credentials"](user_factory("history@example.com"))
    assert (
        client.get(
            "/api/v1/me/reservations",
            params={"cursor": page["next_cursor"]},
            headers=headers(booking, actor=stranger),
        ).status_code
        == 422
    )
    assert (
        client.get("/api/v1/me/reservations", headers=headers(booking, actor=stranger)).json()[
            "items"
        ]
        == []
    )
    for params in [{"limit": 101}, {"limit": 0}, {"cursor": "bad"}]:
        assert (
            client.get(
                "/api/v1/me/reservations", params=params, headers=headers(booking)
            ).status_code
            == 422
        )
    assert_consistent(clean_engine)


def test_organizer_can_hold_and_missing_resources_are_404(client, booking, clean_engine):
    assert booking["execute"](actor_session=booking["owner_session"]).status == 201
    for action in ["hold", "confirm", "cancel"]:
        path = (
            f"/api/v1/events/{uuid4()}/holds"
            if action == "hold"
            else f"/api/v1/reservations/{uuid4()}/{action}"
        )
        assert client.post(path, json={}, headers=headers(booking, action)).status_code == 404
    assert client.get(f"/api/v1/events/{uuid4()}/availability").status_code == 404
    assert_consistent(clean_engine)
