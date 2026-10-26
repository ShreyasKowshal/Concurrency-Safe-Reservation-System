"""Deterministic PostgreSQL contention, rollback, and independent API process evidence."""

import json
import multiprocessing
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Barrier, local
from threading import Event as Signal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from sqlalchemy import event as sql_event
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_event_transactions import wait_until_blocked
from test_reservations import assert_consistent, headers, seed_reservation

from csrs.auth.service import database_time
from csrs.models import Event, IdempotencyRecord, Reservation, SessionRecord, User
from csrs.reservations import service

pytestmark = pytest.mark.integration


def _serve(settings_values, listener, ready):
    import uvicorn

    from csrs.config import Settings
    from csrs.main import create_app

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.send("ready")
            ready.close()

    Server(
        uvicorn.Config(
            create_app(Settings(**settings_values)), log_level="critical", access_log=False
        )
    ).run(sockets=[listener])


@contextmanager
def api_processes(settings, count=2):
    """Spawned interpreters each own an app/engine/pool. Pipes signal actual startup."""
    context = multiprocessing.get_context("spawn")
    processes, listeners, addresses, readers = [], [], [], []
    try:
        for _ in range(count):
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            receive, send = context.Pipe(duplex=False)
            process = context.Process(
                target=_serve,
                args=(
                    settings.model_dump(mode="json")
                    | {
                        "database_url": settings.database_url.get_secret_value(),
                        "redis_url": settings.redis_url.get_secret_value(),
                    },
                    listener,
                    send,
                ),
            )
            process.start()
            send.close()
            processes.append(process)
            listeners.append(listener)
            readers.append(receive)
            addresses.append(f"http://127.0.0.1:{listener.getsockname()[1]}")
        for reader in readers:
            assert reader.poll(20), "API subprocess did not start"
            assert reader.recv() == "ready"
        yield addresses
    finally:
        for process in processes:
            process.terminate()
            process.join(timeout=10)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        for resource in [*listeners, *readers]:
            resource.close()


def http_post(url, request_headers):
    request = Request(
        url, data=b"{}", headers=request_headers | {"Content-Type": "application/json"}
    )
    try:
        response = urlopen(request, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response), response.headers.get("Idempotency-Replayed")


@pytest.mark.parametrize("capacity,attempts", [(1, 50), (20, 100)])
def test_final_seats_across_two_api_processes(
    booking,
    clean_engine,
    postgres_settings,
    user_factory,
    capacity,
    attempts,
):
    with Session(clean_engine) as db, db.begin():
        db.get(Event, booking["event"].id).capacity = capacity
    identities = [
        booking["credentials"](user_factory(f"contender{i}@example.com")) for i in range(attempts)
    ]
    start = Barrier(attempts)
    with api_processes(postgres_settings) as addresses:

        def attempt(index):
            start.wait(timeout=20)
            return http_post(
                f"{addresses[index % 2]}/api/v1/events/{booking['event'].id}/holds",
                headers(booking, f"seat-{index}", identities[index]),
            )

        with ThreadPoolExecutor(max_workers=attempts) as pool:
            replies = list(pool.map(attempt, range(attempts)))
    assert sum(status == 201 for status, _, _ in replies) == capacity
    assert (
        sum(status == 409 and body["error"]["code"] == "EVENT_FULL" for status, body, _ in replies)
        == attempts - capacity
    ), [(status, body) for status, body, _ in replies if status not in {201, 409}]
    with Session(clean_engine) as db:
        assert db.get(Event, booking["event"].id).allocated_seats == capacity
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == attempts
    assert_consistent(clean_engine)


@pytest.mark.parametrize("mode", ["same-key", "different-key", "different-path"])
def test_concurrent_duplicates_across_api_processes(
    booking, clean_engine, postgres_settings, event_factory, mode
):
    another = event_factory(booking["owner"], status="PUBLISHED")
    start = Barrier(10)
    with api_processes(postgres_settings) as addresses:

        def attempt(index):
            key = f"key-{index}" if mode == "different-key" else "one-key"
            resource = another.id if mode == "different-path" and index % 2 else booking["event"].id
            start.wait(timeout=20)
            return http_post(
                f"{addresses[index % 2]}/api/v1/events/{resource}/holds", headers(booking, key)
            )

        with ThreadPoolExecutor(max_workers=10) as pool:
            replies = list(pool.map(attempt, range(10)))
    if mode == "same-key":
        assert all(status == 201 for status, _, _ in replies)
        assert len({body["id"] for _, body, _ in replies}) == 1
        assert sum(replayed == "false" for _, _, replayed in replies) == 1
    else:
        code = "ACTIVE_RESERVATION_EXISTS" if mode == "different-key" else "IDEMPOTENCY_KEY_REUSED"
        expected_success = 1 if mode == "different-key" else 5
        assert sum(status == 201 for status, _, _ in replies) == expected_success
        assert all(status == 201 or body["error"]["code"] == code for status, body, _ in replies)
    assert_consistent(clean_engine)


def ordered_commands(
    monkeypatch, engine, booking, first, second, first_time=None, second_time=None
):
    """Hold first's actual event lock until PostgreSQL observes second waiting on it."""
    acquired, release = Signal(), Signal()
    owner_pid = []
    original_time = service.database_time

    def controlled_time(db):
        now = original_time(db)
        if db.info.get("first"):
            owner_pid.append(db.scalar(select(func.pg_backend_pid())))
            acquired.set()
            assert release.wait(10)
            return first_time or now
        return second_time or now

    monkeypatch.setattr(service, "database_time", controlled_time)

    def run(spec, first=False):
        action, resource, key = spec
        actor = booking["session"]
        with Session(engine, expire_on_commit=False) as db:
            db.info["first"] = first
            return service.command(db, actor.cookie, actor.csrf_token, resource, action, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future1 = pool.submit(run, first, True)
        try:
            assert acquired.wait(5)
            future2 = pool.submit(run, second)
            wait_until_blocked(engine, owner_pid[0])
        finally:
            release.set()
        return future1.result(timeout=10), future2.result(timeout=10)


@pytest.mark.parametrize("first", ["confirm", "cancel"])
def test_confirmation_cancellation_both_lock_orderings(booking, clean_engine, monkeypatch, first):
    row = seed_reservation(clean_engine, booking)
    second = "cancel" if first == "confirm" else "confirm"
    results = ordered_commands(
        monkeypatch, clean_engine, booking, (first, row.id, "first"), (second, row.id, "second")
    )
    assert results[0].status == 200
    assert results[1].status == (200 if second == "cancel" else 409)
    with Session(clean_engine) as db:
        assert db.get(Reservation, row.id).status == "CANCELLED"
        assert db.get(Event, row.event_id).allocated_seats == 0
    assert_consistent(clean_engine)


@pytest.mark.parametrize("action", ["confirm", "cancel"])
@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_repeat_transitions(booking, clean_engine, monkeypatch, action, same_key):
    row = seed_reservation(clean_engine, booking)
    first, second = ordered_commands(
        monkeypatch,
        clean_engine,
        booking,
        (action, row.id, "repeat"),
        (action, row.id, "repeat" if same_key else "new-key"),
    )
    assert first.status == second.status == 200
    assert second.replayed == same_key
    if same_key:
        assert second.body == first.body
    assert_consistent(clean_engine)


def test_duplicate_wait_rechecks_authentication_before_replay(booking, clean_engine, monkeypatch):
    acquired, release = Signal(), Signal()
    original = service.database_time
    owner_pids = []

    def pause(db):
        if db.info.get("first"):
            owner_pids.append(db.scalar(select(func.pg_backend_pid())))
            acquired.set()
            assert release.wait(10)
        return original(db)

    monkeypatch.setattr(service, "database_time", pause)
    actor = booking["session"]

    def execute(first):
        with Session(clean_engine) as db:
            db.info["first"] = first
            return service.command(
                db, actor.cookie, actor.csrf_token, booking["event"].id, "hold", "duplicate"
            )

    from csrs.auth.errors import AuthError

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute, True)
        try:
            assert acquired.wait(5)
            second = pool.submit(execute, False)
            # First is paused after all post-lock auth checks. Observe key-claim blocking.
            wait_until_blocked(clean_engine, owner_pids[0])
            with clean_engine.begin() as connection:
                connection.execute(update(SessionRecord).values(revoked_at=func.clock_timestamp()))
        finally:
            release.set()
        assert first.result(timeout=5).status == 201
        with pytest.raises(AuthError) as error:
            second.result(timeout=5)
        assert error.value.status == 401
    assert_consistent(clean_engine)


@pytest.mark.parametrize("action", ["confirm", "cancel"])
@pytest.mark.parametrize("cleanup_first", [True, False])
def test_expiry_races_and_single_release(booking, clean_engine, monkeypatch, action, cleanup_first):
    row = seed_reservation(clean_engine, booking)
    action_spec = (action, row.id, "transition")
    # A request-time hold cleans the expired row and tries to book a replacement.
    cleanup_spec = ("hold", row.event_id, "replacement")
    if cleanup_first:
        first, second = cleanup_spec, action_spec
        time1 = time2 = row.hold_expires_at
    else:
        first, second = action_spec, cleanup_spec
        time1, time2 = row.hold_expires_at - timedelta(microseconds=1), row.hold_expires_at
    results = ordered_commands(monkeypatch, clean_engine, booking, first, second, time1, time2)
    if cleanup_first:
        assert results[0].status == 201
        assert results[1].status == (409 if action == "confirm" else 200)
    else:
        assert results[0].status == 200
        assert results[1].status == (409 if action == "confirm" else 201)
    assert_consistent(clean_engine)


def order_calls(engine, first, second):
    acquired, release = Signal(), Signal()
    state = local()
    pids = []

    def after_lock(connection, cursor, statement, parameters, context, executemany):
        if (
            getattr(state, "first", False)
            and "FROM events" in statement
            and "FOR UPDATE" in statement
        ):
            state.first = False
            pids.append(connection.exec_driver_sql("SELECT pg_backend_pid()").scalar())
            acquired.set()
            assert release.wait(10)

    def run_first():
        state.first = True
        return first()

    sql_event.listen(engine, "after_cursor_execute", after_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            initial = pool.submit(run_first)
            try:
                assert acquired.wait(5)
                following = pool.submit(second)
                wait_until_blocked(engine, pids[0])
            finally:
                release.set()
            return initial.result(timeout=10), following.result(timeout=10)
    finally:
        sql_event.remove(engine, "after_cursor_execute", after_lock)


@pytest.mark.parametrize("operation", ["capacity", "close"])
@pytest.mark.parametrize("organizer_first", [True, False])
def test_organizer_change_racing_admission(
    booking, clean_engine, user_factory, operation, organizer_first
):
    from csrs.events import service as event_service

    event_id = booking["event"].id
    seed_reservation(clean_engine, booking, "CONFIRMED")
    contender = booking["credentials"](user_factory("racer@example.com"))
    with Session(clean_engine) as db, db.begin():
        db.get(Event, event_id).capacity = 2

    def organizer():
        actor = booking["owner_session"]
        with Session(clean_engine) as db:
            try:
                if operation == "capacity":
                    event_service.change_capacity(db, actor.cookie, actor.csrf_token, event_id, 1)
                else:
                    event_service.close_event(db, actor.cookie, actor.csrf_token, event_id)
                return 200
            except event_service.EventError as error:
                return error.status

    def admission():
        return booking["execute"](actor_session=contender)

    if organizer_first:
        first, second = order_calls(clean_engine, organizer, admission)
        assert first == 200 and second.status == 409
        assert second.body["error"]["code"] == (
            "EVENT_FULL" if operation == "capacity" else "BOOKING_CLOSED"
        )
    else:
        first, second = order_calls(clean_engine, admission, organizer)
        assert first.status == 201 and second == (409 if operation == "capacity" else 200)
    assert_consistent(clean_engine)


@pytest.mark.parametrize("change", ["expired", "revoked", "inactive", "deadline", "closed"])
def test_hold_rechecks_after_event_lock_wait(client, booking, clean_engine, change):
    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(clean_engine) as holder, holder.begin():
            event = holder.scalar(
                select(Event).where(Event.id == booking["event"].id).with_for_update()
            )
            pid = holder.scalar(select(func.pg_backend_pid()))
            future = pool.submit(
                client.post, f"/api/v1/events/{event.id}/holds", json={}, headers=headers(booking)
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
            elif change == "inactive":
                holder.execute(
                    update(User).where(User.id == booking["user"].id).values(is_active=False)
                )
            elif change == "deadline":
                event.booking_closes_at = now
            else:
                event.status = "CLOSED"
        result = future.result(timeout=5)
    assert result.status_code == (409 if change in {"deadline", "closed"} else 401)
    assert_consistent(clean_engine)


def test_confirm_uses_post_wait_time_not_transaction_start(client, booking, clean_engine):
    row = seed_reservation(clean_engine, booking)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(clean_engine) as holder, holder.begin():
            holder.scalar(select(Event).where(Event.id == row.event_id).with_for_update())
            pid = holder.scalar(select(func.pg_backend_pid()))
            future = pool.submit(
                client.post,
                f"/api/v1/reservations/{row.id}/confirm",
                json={},
                headers=headers(booking),
            )
            wait_until_blocked(clean_engine, pid)
            with clean_engine.connect() as observer:
                transaction_start = observer.scalar(
                    text(
                        "SELECT xact_start FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND :blocker = ANY(pg_blocking_pids(pid))"
                    ),
                    {"blocker": pid},
                )
            assert transaction_start is not None
            observed_at = database_time(holder)
            window = observed_at - transaction_start
            assert window >= timedelta(microseconds=2)
            # A stale transaction clock sees a valid hold; the post-lock clock must not.
            deadline = transaction_start + window / 2
            holder.get(Reservation, row.id).hold_expires_at = deadline
            holder.flush()
            before_release = database_time(holder)
            assert transaction_start < deadline < observed_at <= before_release
        result = future.result(timeout=5)
    assert result.status_code == 409 and result.json()["error"]["code"] == "HOLD_EXPIRED"
    with Session(clean_engine) as db:
        stored = db.get(Reservation, row.id)
        assert stored.status == "EXPIRED" and stored.confirmed_at is None
        assert stored.hold_expires_at == deadline
        assert stored.expired_at >= before_release
        outcome = db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == booking["user"].id,
                IdempotencyRecord.key == "request-key",
            )
        )
        assert outcome.response_status == 409 and outcome.response_body == result.json()
        assert outcome.completed_at == stored.expired_at
    assert_consistent(clean_engine)


def test_lock_timeout_rolls_back_claim_and_same_key_retries(
    client_factory, booking, clean_engine, postgres_settings
):
    settings = type(postgres_settings)(
        **(postgres_settings.model_dump() | {"db_statement_timeout_ms": 100})
    )
    with client_factory(settings=settings) as client, ThreadPoolExecutor(max_workers=1) as pool:
        path = f"/api/v1/events/{booking['event'].id}/holds"
        with Session(clean_engine) as holder, holder.begin():
            holder.scalar(select(Event).where(Event.id == booking["event"].id).with_for_update())
            reply = pool.submit(client.post, path, json={}, headers=headers(booking)).result(
                timeout=5
            )
            assert reply.status_code == 503 and "SELECT" not in reply.text
            assert_consistent(clean_engine)
        assert client.post(path, json={}, headers=headers(booking)).status_code == 201
    assert_consistent(clean_engine)


@pytest.mark.parametrize("stage", ["row", "counter", "outcome", "before-commit"])
@pytest.mark.parametrize("cleanup", [False, True])
def test_injected_failure_rolls_back_every_piece(
    booking, clean_engine, monkeypatch, stage, cleanup
):
    due = seed_reservation(clean_engine, booking, due=True) if cleanup else None

    def fail(db, *args):
        if stage == "row" and any(isinstance(row, Reservation) for row in db.new):
            raise RuntimeError("injected row failure")
        if stage == "outcome" and any(
            isinstance(row, IdempotencyRecord) and row.completed_at for row in db.dirty
        ):
            raise RuntimeError("injected outcome failure")
        if stage == "before-commit":
            raise RuntimeError("injected before-commit failure")

    name = "before_commit" if stage == "before-commit" else "after_flush"
    original = service._apply

    def fail_after_counter(*args):
        original(*args)
        raise RuntimeError("injected counter failure")

    if stage == "counter":
        monkeypatch.setattr(service, "_apply", fail_after_counter)
    else:
        sql_event.listen(Session, name, fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            booking["execute"](key="rollback")
    finally:
        if stage != "counter":
            sql_event.remove(Session, name, fail)
        monkeypatch.setattr(service, "_apply", original)
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(Reservation)) == int(cleanup)
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
        if cleanup:
            assert db.get(Reservation, due.id).status == "HELD"
    assert_consistent(clean_engine)
    assert booking["execute"](key="rollback").status == 201
    assert_consistent(clean_engine)


@pytest.mark.parametrize("close_first", [True, False])
def test_close_racing_valid_confirmation_preserves_hold(booking, clean_engine, close_first):
    from csrs.events import service as event_service

    row = seed_reservation(clean_engine, booking)
    actor = booking["owner_session"]

    def close():
        with Session(clean_engine) as db:
            return event_service.close_event(db, actor.cookie, actor.csrf_token, row.event_id)

    def confirm():
        return booking["execute"]("confirm", row.id)

    order_calls(clean_engine, close if close_first else confirm, confirm if close_first else close)
    with Session(clean_engine) as db:
        assert db.get(Event, row.event_id).status == "CLOSED"
        assert db.get(Reservation, row.id).status == "CONFIRMED"
    assert_consistent(clean_engine)


@pytest.mark.parametrize("committed", [True, False])
def test_uncertain_commit_same_key_recovers_without_second_allocation(
    booking, clean_engine, committed
):
    def lost(db):
        raise OperationalError("COMMIT", {}, OSError("injected connection lost"))

    name = "after_commit" if committed else "before_commit"
    sql_event.listen(Session, name, lost)
    try:
        with pytest.raises(OperationalError):
            booking["execute"](key="uncertain")
    finally:
        sql_event.remove(Session, name, lost)
    retry = booking["execute"](key="uncertain")
    assert retry.status == 201 and retry.replayed == committed
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(Reservation)) == 1
    assert_consistent(clean_engine)


def test_response_lost_after_commit_before_http_send(client, booking, clean_engine, monkeypatch):
    from csrs.api import reservations as routes

    original = routes.JSONResponse

    def lost_response(*args, **kwargs):
        raise OSError("injected lost HTTP response")

    monkeypatch.setattr(routes, "JSONResponse", lost_response)
    path = f"/api/v1/events/{booking['event'].id}/holds"
    with pytest.raises(OSError, match="lost HTTP response"):
        client.post(path, json={}, headers=headers(booking))
    monkeypatch.setattr(routes, "JSONResponse", original)
    retry = client.post(path, json={}, headers=headers(booking))
    assert retry.status_code == 201 and retry.headers["idempotency-replayed"] == "true"
    assert_consistent(clean_engine)
