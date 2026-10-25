"""Real lock waits and commits, not mocked database proofs or booking implementation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from time import monotonic, sleep

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from csrs.auth.service import database_time
from csrs.events import service
from csrs.models import Event, Reservation, Role, SessionRecord, User

pytestmark = pytest.mark.integration
BASE = "/api/v1/organizer/events"


def wait_until_blocked(engine, blocker_pid):
    """Poll observed PostgreSQL lock state; do not guess ordering with an arbitrary sleep."""
    deadline = monotonic() + 2
    with engine.connect() as observer:
        while monotonic() < deadline:
            waiting = observer.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND :pid = ANY(pg_blocking_pids(pid))"
                ),
                {"pid": blocker_pid},
            )
            observer.rollback()
            if waiting:
                return
            sleep(0.01)
    pytest.fail("The contender never waited on the expected PostgreSQL event lock")


@pytest.mark.parametrize("action", ["capacity", "edit", "publish", "close"])
def test_event_command_waits_for_lock_and_rereads_committed_state(
    client, user_factory, event_factory, login_headers, clean_engine, action
):
    owner = user_factory(role=Role.ORGANIZER)
    headers = login_headers(client, owner.normalized_email)
    event = event_factory(owner, status="PUBLISHED" if action in {"capacity", "close"} else "DRAFT")
    attendees = [user_factory(f"seat{i}@example.com") for i in range(3)]
    url = f"{BASE}/{event.id}"
    if action != "edit":
        url += "/" + action
    body = (
        {"capacity": 2}
        if action == "capacity"
        else {"title": "Waiting edit"}
        if action == "edit"
        else {}
    )
    method = "PATCH" if action in {"capacity", "edit"} else "POST"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(clean_engine) as holder, holder.begin():
            locked = holder.scalar(select(Event).where(Event.id == event.id).with_for_update())
            blocker_pid = holder.scalar(select(func.pg_backend_pid()))
            future = pool.submit(client.request, method, url, json=body, headers=headers)
            wait_until_blocked(clean_engine, blocker_pid)
            if action == "capacity":
                # Simulate a future allocator following the event lock, only as test data.
                # These are real consistent rows, not a claim that a hold API exists.
                now = database_time(holder)
                for attendee in attendees:
                    holder.add(
                        Reservation(
                            event_id=event.id,
                            user_id=attendee.id,
                            status="CONFIRMED",
                            created_at=now - timedelta(minutes=1),
                            hold_expires_at=now + timedelta(minutes=4),
                            confirmed_at=now,
                        )
                    )
                locked.allocated_seats = 3
            elif action == "publish":
                locked.booking_closes_at = database_time(holder) - timedelta(minutes=1)
            else:
                locked.status = "CLOSED"
        response = future.result(timeout=5)

    assert response.status_code == 409
    expected = {"capacity": "CAPACITY_BELOW_ALLOCATED", "publish": "EVENT_NOT_PUBLISHABLE"}.get(
        action, "INVALID_EVENT_STATE"
    )
    assert response.json()["error"]["code"] == expected
    with Session(clean_engine) as db:
        stored = db.get(Event, event.id)
        assert stored.title == event.title and stored.capacity == 10
        if action == "capacity":
            count = db.scalar(
                select(func.count())
                .select_from(Reservation)
                .where(Reservation.event_id == event.id)
            )
            assert stored.allocated_seats == count == 3


@pytest.mark.parametrize("change", ["expired", "revoked", "inactive", "demoted"])
def test_authentication_is_rechecked_after_event_lock_wait(
    client, user_factory, event_factory, login_headers, clean_engine, change
):
    owner = user_factory(role=Role.ORGANIZER)
    headers = login_headers(client, owner.normalized_email)
    event = event_factory(owner)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(clean_engine) as holder, holder.begin():
            holder.scalar(select(Event).where(Event.id == event.id).with_for_update())
            pid = holder.scalar(select(func.pg_backend_pid()))
            future = pool.submit(
                client.patch, f"{BASE}/{event.id}", json={"title": "Denied"}, headers=headers
            )
            wait_until_blocked(clean_engine, pid)
            now = database_time(holder)
            if change == "expired":
                holder.execute(
                    update(SessionRecord).values(
                        created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1)
                    )
                )
            elif change == "revoked":
                holder.execute(update(SessionRecord).values(revoked_at=now))
            else:
                holder.execute(
                    update(User)
                    .where(User.id == owner.id)
                    .values(
                        **({"is_active": False} if change == "inactive" else {"role": "ATTENDEE"})
                    )
                )
        response = future.result(timeout=5)
    assert response.status_code == (403 if change == "demoted" else 401)
    with Session(clean_engine) as db:
        assert db.get(Event, event.id).title == event.title


def test_event_statement_timeout_is_sanitized_rolls_back_and_allows_retry(
    client_factory, user_factory, event_factory, login_headers, clean_engine, postgres_settings
):
    owner = user_factory(role=Role.ORGANIZER)
    event = event_factory(owner)
    settings = type(postgres_settings)(
        **(postgres_settings.model_dump() | {"db_statement_timeout_ms": 100})
    )
    with client_factory(settings=settings) as client:
        headers = login_headers(client, owner.normalized_email)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with Session(clean_engine) as holder, holder.begin():
                holder.scalar(select(Event).where(Event.id == event.id).with_for_update())
                future = pool.submit(
                    client.patch,
                    f"{BASE}/{event.id}/capacity",
                    json={"capacity": 20},
                    headers=headers,
                )
                reply = future.result(timeout=5)
                assert reply.status_code == 503
                assert reply.json()["error"]["code"] == "TEMPORARILY_UNAVAILABLE"
                assert "SELECT" not in reply.text and "psycopg" not in reply.text
            retry = client.patch(
                f"{BASE}/{event.id}/capacity", json={"capacity": 20}, headers=headers
            )
            assert retry.status_code == 200


@pytest.mark.parametrize("action", ["create", "edit", "capacity", "publish", "close"])
def test_fault_after_event_flush_rolls_back_before_success(
    client, user_factory, event_factory, login_headers, clean_engine, monkeypatch, action
):
    owner = user_factory(role=Role.ORGANIZER)
    headers = login_headers(client, owner.normalized_email)
    event = event_factory(owner, status="PUBLISHED" if action == "close" else "DRAFT")
    body = {"title": "Changed"}
    if action == "create":
        body = {
            "title": "New event",
            "location": event.location,
            "capacity": 20,
            "starts_at": event.starts_at.isoformat(),
            "ends_at": event.ends_at.isoformat(),
            "booking_closes_at": event.booking_closes_at.isoformat(),
        }
    elif action == "capacity":
        body = {"capacity": 20}
    elif action in {"publish", "close"}:
        body = {}
    url = BASE if action == "create" else f"{BASE}/{event.id}"
    if action in {"capacity", "publish", "close"}:
        url += "/" + action

    def fail(cls, event):
        raise RuntimeError("injected after flush, before commit")

    monkeypatch.setattr(service.OrganizerEvent, "model_validate", classmethod(fail))
    with pytest.raises(RuntimeError, match="injected after flush"):
        client.request(
            "PATCH" if action in {"edit", "capacity"} else "POST", url, json=body, headers=headers
        )
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(Event)) == 1
        stored = db.get(Event, event.id)
        assert stored.title == event.title and stored.status == event.status
        assert stored.capacity == 10 and stored.allocated_seats == 0
