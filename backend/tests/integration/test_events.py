from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from csrs.auth.service import database_time
from csrs.models import Event, Reservation, Role, SessionRecord, User

pytestmark = pytest.mark.integration
BASE = "/api/v1/organizer/events"
PUBLIC = "/api/v1/events"


@pytest.fixture
def organizer(client, user_factory, login_headers):
    owner = user_factory("organizer@example.com", role=Role.ORGANIZER)
    return owner, login_headers(client, owner.normalized_email)


def body_from(event):
    return {
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat(),
        "booking_closes_at": event.booking_closes_at.isoformat(),
        "capacity": event.capacity,
    }


def test_organizer_creates_draft_with_server_owned_state(client, organizer, event_factory, db):
    owner, headers = organizer
    template = event_factory(owner)
    body = body_from(template) | {"title": "  New workshop  "}
    body.pop("description")
    reply = client.post(BASE, json=body, headers=headers)
    assert reply.status_code == 201
    saved = reply.json()
    assert saved["organizer_id"] == str(owner.id)
    assert saved["status"] == "DRAFT" and saved["allocated_seats"] == 0
    assert saved["description"] == "" and saved["title"] == "New workshop"
    assert reply.headers["cache-control"] == "no-store"
    with db.begin():
        event = db.get(Event, saved["id"])
        assert event is not None and event.organizer_id == owner.id
        assert event.status == "DRAFT" and event.capacity == 10


@pytest.mark.parametrize("anonymous", [True, False])
def test_anonymous_and_attendee_cannot_create_or_read_organizer_events(
    client, user_factory, event_factory, login_headers, anonymous
):
    owner = user_factory("owner@example.com", role=Role.ORGANIZER)
    event = event_factory(owner)
    if anonymous:
        token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        headers = {"Origin": "http://localhost:5173", "X-CSRF-Token": token}
    else:
        attendee = user_factory()
        headers = login_headers(client, attendee.normalized_email)
    expected = 401 if anonymous else 403
    assert client.post(BASE, json=body_from(event), headers=headers).status_code == expected
    assert client.get(BASE).status_code == expected
    assert client.get(f"{BASE}/{event.id}").status_code == expected


@pytest.mark.parametrize("status", ["DRAFT", "PUBLISHED", "CLOSED"])
def test_public_visibility_and_owner_detail(client, organizer, event_factory, status):
    owner, _ = organizer
    event = event_factory(owner, status=status)
    client.cookies.clear()
    detail = client.get(f"{PUBLIC}/{event.id}")
    page = client.get(PUBLIC)
    assert page.status_code == 200
    if status == "PUBLISHED":
        assert detail.status_code == 200 and len(page.json()["items"]) == 1
        assert set(detail.json()) == {
            "id",
            "title",
            "location",
            "starts_at",
            "booking_closes_at",
            "status",
            "capacity",
            "description",
            "ends_at",
            "organizer_id",
        }
        assert "allocated_seats" not in page.text
    else:
        assert detail.status_code == 404 and page.json()["items"] == []
        assert event.title not in detail.text


def test_own_list_and_detail_include_private_states_only_for_owner(
    client, organizer, user_factory, event_factory
):
    owner, _ = organizer
    other = user_factory("other@example.com", role=Role.ORGANIZER)
    events = [event_factory(owner, status=status) for status in ("DRAFT", "PUBLISHED", "CLOSED")]
    hidden = event_factory(other)
    page = client.get(BASE)
    assert {e["id"] for e in page.json()["items"]} == {str(e.id) for e in events}
    assert page.headers["cache-control"] == "no-store"
    for event in events:
        detail = client.get(f"{BASE}/{event.id}")
        assert detail.status_code == 200 and detail.json()["allocated_seats"] == 0
    assert client.get(f"{BASE}/{hidden.id}").status_code == 404


@pytest.mark.parametrize("operation", ["detail", "edit", "capacity", "publish", "close"])
def test_other_organizer_cannot_access_private_event(
    client, organizer, user_factory, event_factory, operation, db
):
    _, headers = organizer
    other = user_factory("other@example.com", role=Role.ORGANIZER)
    event = event_factory(other)
    url = f"{BASE}/{event.id}"
    if operation == "detail":
        result = client.get(url)
    elif operation == "edit":
        result = client.patch(url, json={"title": "Stolen event"}, headers=headers)
    elif operation == "capacity":
        result = client.patch(url + "/capacity", json={"capacity": 15}, headers=headers)
    else:
        result = client.post(url + "/" + operation, json={}, headers=headers)
    assert result.status_code == 404 and result.json()["error"]["code"] == "NOT_FOUND"
    assert event.title not in result.text
    with db.begin():
        stored = db.get(Event, event.id)
        assert stored.organizer_id == other.id and stored.title == event.title
        assert stored.status == "DRAFT" and stored.capacity == 10


@pytest.mark.parametrize(
    "field,value",
    [
        ("capacity", 0),
        ("capacity", -1),
        ("capacity", True),
        ("capacity", "10"),
        ("capacity", 2147483648),
        ("title", " "),
        ("location", ""),
        ("starts_at", "2035-01-01T10:00:00"),
        ("ends_at", "invalid"),
        ("organizer_id", str(uuid4())),
        ("status", "PUBLISHED"),
        ("allocated_seats", 1),
    ],
)
def test_invalid_creation_is_rejected_without_new_event(
    client, organizer, event_factory, db, field, value
):
    owner, headers = organizer
    template = event_factory(owner)
    reply = client.post(BASE, json=body_from(template) | {field: value}, headers=headers)
    assert reply.status_code == 422
    assert all(set(error) == {"type", "loc", "msg"} for error in reply.json()["detail"])
    with db.begin():
        assert db.scalar(select(func.count()).select_from(Event)) == 1


def test_create_and_patch_reject_bad_combined_schedules_atomically(
    client, organizer, event_factory, db
):
    owner, headers = organizer
    event = event_factory(owner)
    body = body_from(event)
    assert (
        client.post(BASE, json=body | {"ends_at": body["starts_at"]}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            BASE, json=body | {"booking_closes_at": body["ends_at"]}, headers=headers
        ).status_code
        == 422
    )
    reply = client.patch(
        f"{BASE}/{event.id}",
        json={"title": "Must roll back", "ends_at": body["booking_closes_at"]},
        headers=headers,
    )
    assert reply.status_code == 422 and reply.json()["error"]["code"] == "INVALID_EVENT_SCHEDULE"
    with db.begin():
        stored = db.get(Event, event.id)
        assert stored.title == event.title and stored.ends_at == event.ends_at


def test_draft_metadata_and_schedule_edit_then_published_metadata_edit(
    client, organizer, event_factory
):
    owner, headers = organizer
    event = event_factory(owner)
    url = f"{BASE}/{event.id}"
    change = {
        "title": "Updated",
        "description": "",
        "location": "Room 202",
        "starts_at": (event.starts_at + timedelta(hours=1)).isoformat(),
        "ends_at": (event.ends_at + timedelta(hours=1)).isoformat(),
        "booking_closes_at": (event.booking_closes_at + timedelta(hours=1)).isoformat(),
    }
    edited = client.patch(url, json=change, headers=headers)
    assert edited.status_code == 200 and edited.json()["title"] == "Updated"
    assert client.post(url + "/publish", json={}, headers=headers).status_code == 200
    result = client.patch(
        url,
        json={
            "description": "Published details",
            "ends_at": (event.ends_at + timedelta(hours=2)).isoformat(),
        },
        headers=headers,
    )
    assert result.status_code == 200 and result.json()["description"] == "Published details"
    assert result.json()["organizer_id"] == str(owner.id)


@pytest.mark.parametrize("field", ["starts_at", "booking_closes_at"])
def test_published_start_and_deadline_are_immutable(client, organizer, event_factory, field):
    owner, headers = organizer
    event = event_factory(owner, status="PUBLISHED")
    result = client.patch(
        f"{BASE}/{event.id}", json={field: getattr(event, field).isoformat()}, headers=headers
    )
    assert (
        result.status_code == 409 and result.json()["error"]["code"] == "EVENT_SCHEDULE_IMMUTABLE"
    )


@pytest.mark.parametrize(
    "status,action,expected",
    [
        ("DRAFT", "publish", 200),
        ("PUBLISHED", "publish", 409),
        ("CLOSED", "publish", 409),
        ("DRAFT", "close", 409),
        ("PUBLISHED", "close", 200),
        ("CLOSED", "close", 409),
    ],
)
def test_only_forward_lifecycle_transitions(
    client, organizer, event_factory, status, action, expected
):
    owner, headers = organizer
    event = event_factory(owner, status=status)
    reply = client.post(f"{BASE}/{event.id}/{action}", json={}, headers=headers)
    assert reply.status_code == expected
    detail = client.get(f"{BASE}/{event.id}").json()
    desired = {"publish": "PUBLISHED", "close": "CLOSED"}[action] if expected == 200 else status
    assert detail["status"] == desired and detail["allocated_seats"] == 0
    assert client.get(f"{PUBLIC}/{event.id}").status_code == (
        200 if desired == "PUBLISHED" else 404
    )


def test_draft_may_be_stale_but_publication_rechecks_database_time(
    client, organizer, event_factory, monkeypatch
):
    owner, headers = organizer
    event = event_factory(owner)
    # Equality is not a future booking deadline; no sleeps or browser-clock assumption.
    monkeypatch.setattr("csrs.events.service.database_time", lambda db: event.booking_closes_at)
    result = client.post(f"{BASE}/{event.id}/publish", json={}, headers=headers)
    assert result.status_code == 409 and result.json()["error"]["code"] == "EVENT_NOT_PUBLISHABLE"
    assert client.get(f"{BASE}/{event.id}").json()["status"] == "DRAFT"


def test_stale_draft_creation_is_allowed_but_cannot_publish_against_real_database_clock(
    client, organizer, event_factory
):
    owner, headers = organizer
    template = event_factory(owner)
    body = body_from(template)
    for field in ("starts_at", "ends_at", "booking_closes_at"):
        body[field] = (getattr(template, field) - timedelta(days=10)).isoformat()
    created = client.post(BASE, json=body, headers=headers)
    assert created.status_code == 201
    result = client.post(f"{BASE}/{created.json()['id']}/publish", json={}, headers=headers)
    assert result.status_code == 409 and result.json()["error"]["code"] == "EVENT_NOT_PUBLISHABLE"


@pytest.mark.parametrize("operation", ["edit", "publish", "close", "capacity"])
def test_mutation_rejects_forged_ownership_state_and_empty_patch(
    client, organizer, event_factory, operation
):
    owner, headers = organizer
    event = event_factory(owner)
    url = f"{BASE}/{event.id}" + ("" if operation == "edit" else "/" + operation)
    method = "PATCH" if operation in {"edit", "capacity"} else "POST"
    bodies = [{"organizer_id": str(uuid4())}, {"status": "PUBLISHED"}, {"allocated_seats": 1}]
    if operation in {"edit", "capacity"}:
        bodies.append({})
    for body in bodies:
        result = client.request(method, url, json=body, headers=headers)
        assert result.status_code == 422


@pytest.mark.parametrize("operation", ["edit", "capacity"])
def test_closed_events_are_read_only(client, organizer, event_factory, operation):
    owner, headers = organizer
    event = event_factory(owner, status="CLOSED")
    url = f"{BASE}/{event.id}" + ("/capacity" if operation == "capacity" else "")
    result = client.patch(
        url, json={"capacity": 20} if operation == "capacity" else {"title": "New"}, headers=headers
    )
    assert result.status_code == 409 and result.json()["error"]["code"] == "INVALID_EVENT_STATE"


@pytest.mark.parametrize("operation", ["create", "edit", "capacity", "publish", "close"])
@pytest.mark.parametrize(
    "failure", ["token", "mismatch", "cookie", "origin", "missing_origin", "media_type"]
)
def test_every_event_mutation_enforces_session_csrf_source_and_json(
    client, organizer, event_factory, operation, failure
):
    owner, headers = organizer
    event = event_factory(owner, status="PUBLISHED" if operation == "close" else "DRAFT")
    headers = headers.copy()
    body = {
        "create": body_from(event),
        "edit": {"title": "New"},
        "capacity": {"capacity": 20},
        "publish": {},
        "close": {},
    }[operation]
    url = BASE if operation == "create" else f"{BASE}/{event.id}"
    if operation in {"capacity", "publish", "close"}:
        url += "/" + operation
    if failure == "token":
        headers.pop("X-CSRF-Token")
    elif failure == "mismatch":
        headers["X-CSRF-Token"] = "0" * 64
    elif failure == "cookie":
        client.cookies.clear()
    elif failure == "origin":
        headers["Origin"] = "https://untrusted.example"
    elif failure == "missing_origin":
        headers.pop("Origin")
    else:
        headers["Content-Type"] = "text/plain"
    result = client.request(
        "PATCH" if operation in {"edit", "capacity"} else "POST", url, json=body, headers=headers
    )
    expected = 401 if failure == "cookie" else 415 if failure == "media_type" else 403
    assert result.status_code == expected
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("failure", ["expired", "revoked", "inactive", "demoted"])
def test_event_mutation_rechecks_current_authentication(
    client, organizer, event_factory, db, failure
):
    owner, headers = organizer
    event = event_factory(owner)
    with db.begin():
        now = database_time(db)
        if failure == "expired":
            db.execute(
                update(SessionRecord).values(
                    created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1)
                )
            )
        elif failure == "revoked":
            db.execute(update(SessionRecord).values(revoked_at=now))
        else:
            db.execute(
                update(User)
                .where(User.id == owner.id)
                .values(**({"is_active": False} if failure == "inactive" else {"role": "ATTENDEE"}))
            )
    result = client.patch(f"{BASE}/{event.id}", json={"title": "Denied"}, headers=headers)
    assert result.status_code == (403 if failure == "demoted" else 401)


def test_keyset_pagination_ties_filters_and_scope(client, organizer, user_factory, event_factory):
    owner, _ = organizer
    other = user_factory("other@example.com", role=Role.ORGANIZER)
    anchor = event_factory(owner, status="PUBLISHED")
    for _ in range(4):
        event_factory(owner, status="PUBLISHED", starts_at=anchor.starts_at)
    event_factory(owner, starts_at=anchor.starts_at)
    event_factory(other, status="PUBLISHED", starts_at=anchor.starts_at)
    seen, cursor = [], None
    while True:
        page = client.get(
            PUBLIC, params={"limit": 2, **({"cursor": cursor} if cursor else {})}
        ).json()
        seen.extend(row["id"] for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 6 and seen == sorted(set(seen))
    private = client.get(BASE, params={"limit": 1}).json()
    assert private["next_cursor"]
    assert client.get(PUBLIC, params={"cursor": private["next_cursor"]}).status_code == 422
    public_cursor = client.get(PUBLIC, params={"limit": 1}).json()["next_cursor"]
    assert client.get(BASE, params={"cursor": public_cursor}).status_code == 422
    assert len(client.get(BASE).json()["items"]) == 6


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": "x"},
        {"cursor": "*"},
        {"cursor": ""},
        {"cursor": "x" * 513},
    ],
)
def test_invalid_pagination_is_rejected(client, params):
    assert client.get(PUBLIC, params=params).status_code == 422


def test_missing_and_malformed_ids_are_safe(client, organizer):
    for base in (BASE, PUBLIC):
        assert client.get(f"{base}/{uuid4()}").status_code == 404
        assert client.get(f"{base}/not-a-uuid").status_code == 422
    assert client.get(f"{PUBLIC}/{uuid4()}/availability").status_code == 404
    assert client.get(f"{BASE}/{uuid4()}/dashboard").status_code == 404
    assert client.post(f"{PUBLIC}/{uuid4()}/holds", json={}).status_code == 404


def test_published_discovery_is_not_a_booking_eligibility_claim(client, organizer, event_factory):
    owner, _ = organizer
    event = event_factory(owner)
    # Stale but structurally valid publication can exist after time passes; it stays public
    # until explicitly closed. No automatic status transition is claimed.
    old = event_factory(
        owner,
        status="PUBLISHED",
        starts_at=event.starts_at - timedelta(days=10),
        ends_at=event.ends_at - timedelta(days=10),
        booking_closes_at=event.booking_closes_at - timedelta(days=10),
    )
    assert client.get(f"{PUBLIC}/{old.id}").status_code == 200


def test_capacity_respects_consistent_seeded_allocations_without_expiring_holds(
    client, organizer, user_factory, event_factory, db
):
    owner, headers = organizer
    event = event_factory(owner, status="PUBLISHED")
    attendees = [user_factory(f"seat{i}@example.com") for i in range(3)]
    with db.begin():
        now = database_time(db)
        for attendee in attendees:
            db.add(
                Reservation(
                    event_id=event.id,
                    user_id=attendee.id,
                    status="HELD",
                    created_at=now - timedelta(hours=2),
                    hold_expires_at=now - timedelta(hours=1),
                )
            )
        db.execute(update(Event).where(Event.id == event.id).values(allocated_seats=3))
    url = f"{BASE}/{event.id}/capacity"
    rejected = client.patch(url, json={"capacity": 2}, headers=headers)
    assert (
        rejected.status_code == 409
        and rejected.json()["error"]["code"] == "CAPACITY_BELOW_ALLOCATED"
    )
    assert client.patch(url, json={"capacity": 3}, headers=headers).status_code == 200
    assert client.patch(url, json={"capacity": 20}, headers=headers).status_code == 200
    with db.begin():
        stored = db.get(Event, event.id)
        assert stored.allocated_seats == 3 and stored.capacity == 20
        assert (
            db.scalar(
                select(func.count()).select_from(Reservation).where(Reservation.status == "HELD")
            )
            == 3
        )
