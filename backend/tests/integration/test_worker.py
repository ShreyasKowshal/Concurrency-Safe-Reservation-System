"""Actual PostgreSQL transactions, index-backed bounds, and worker/API lock races."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event as Signal
from uuid import uuid4

import pytest
from sqlalchemy import event as sql_event
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.orm import Session
from test_event_transactions import wait_until_blocked
from test_reservations import assert_consistent, seed_reservation

from csrs import worker
from csrs.events import service as event_service
from csrs.models import Event, Reservation

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "status,due,expected",
    [
        ("HELD", True, 3),
        ("HELD", False, 0),
        ("CONFIRMED", True, 0),
        ("CANCELLED", True, 0),
        ("EXPIRED", True, 0),
    ],
)
def test_expiration_states_and_repeated_sweeps(
    held_event_factory, clean_engine, status, due, expected
):
    event, rows = held_event_factory(3, status=status, due=due)
    assert worker.expire_event(clean_engine, event.id, 100).expired == expected
    assert worker.expire_event(clean_engine, event.id, 100).expired == 0
    assert_consistent(clean_engine)


@pytest.mark.parametrize("status", ["PUBLISHED", "CLOSED"])
def test_worker_reclaims_unvisited_events(held_event_factory, clean_engine, status):
    event, rows = held_event_factory(4, event_status=status)
    page = worker.discover(clean_engine, 10)
    assert event.id in page.event_ids
    assert worker.expire_event(clean_engine, event.id, 10).expired == 4
    with Session(clean_engine) as db:
        assert db.get(Event, event.id).allocated_seats == 0
    assert_consistent(clean_engine)


def test_bounded_rows_and_keyset_forward_progress_past_busy_oldest_event(
    held_event_factory, clean_engine
):
    oldest, _ = held_event_factory(12)
    later, _ = held_event_factory(5)
    position = None
    with Session(clean_engine) as holder, holder.begin():
        holder.scalar(select(Event).where(Event.id == oldest.id).with_for_update())
        for _ in range(8):
            page = worker.discover(clean_engine, 2, position)
            assert page.scanned <= 2 and len(page.event_ids) <= 2
            position = page.position
            for identifier in page.event_ids:
                result = worker.expire_event(clean_engine, identifier, 2)
                assert result.expired <= 2
            with Session(clean_engine) as db:
                if db.get(Event, later.id).allocated_seats == 0:
                    break
        else:
            pytest.fail("Busy oldest event starved a later due event")
    for _ in range(30):
        page = worker.discover(clean_engine, 2, position)
        position = page.position
        for identifier in page.event_ids:
            worker.expire_event(clean_engine, identifier, 2)
    with Session(clean_engine) as db:
        assert db.get(Event, oldest.id).allocated_seats == 0
        assert db.get(Event, later.id).allocated_seats == 0
    assert_consistent(clean_engine)


def test_pass_cutoff_excludes_newly_overdue_work_until_wrap(held_event_factory, clean_engine):
    first, _ = held_event_factory(2)
    page = worker.discover(clean_engine, 1)
    assert page.position is not None
    second, rows = held_event_factory(1, due=False)
    with Session(clean_engine) as db, db.begin():
        db.get(Reservation, rows[0].id).hold_expires_at = page.position.cutoff + timedelta(
            microseconds=1
        )
    cursor = page.position
    for _ in range(4):
        following = worker.discover(clean_engine, 1, cursor)
        assert second.id not in following.event_ids
        cursor = following.position
        if cursor is None:
            break
    assert second.id in worker.discover(clean_engine, 10).event_ids


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_worker_exact_expiration_boundary(booking, clean_engine, monkeypatch, offset):
    row = seed_reservation(clean_engine, booking)
    decision = row.hold_expires_at + timedelta(microseconds=offset)
    monkeypatch.setattr(worker, "database_time", lambda db: decision)
    result = worker.expire_event(clean_engine, row.event_id, 5)
    assert result.expired == int(offset >= 0)
    assert_consistent(clean_engine)


def test_busy_event_is_skipped_without_reservation_lock(booking, clean_engine):
    row = seed_reservation(clean_engine, booking, due=True)
    with Session(clean_engine) as holder, holder.begin():
        holder.scalar(select(Event).where(Event.id == row.event_id).with_for_update())
        assert worker.expire_event(clean_engine, row.event_id, 1).skipped
        assert holder.get(Reservation, row.id).status == "HELD"
    assert worker.expire_event(clean_engine, row.event_id, 1).expired == 1
    assert worker.expire_event(clean_engine, uuid4(), 1).skipped
    assert_consistent(clean_engine)


@pytest.mark.parametrize("stage", ["rows", "counter", "commit"])
def test_expiration_fault_rolls_back_rows_and_counter(booking, clean_engine, stage):
    row = seed_reservation(clean_engine, booking, due=True)
    fired = []

    def fail(*args):
        if stage == "rows":
            if "UPDATE reservations" not in args[2]:
                return
        fired.append(True)
        raise RuntimeError("injected worker transaction failure")

    target, hook = (
        (clean_engine, "after_cursor_execute")
        if stage == "rows"
        else (Session, "after_flush" if stage == "counter" else "before_commit")
    )
    sql_event.listen(target, hook, fail)
    try:
        with pytest.raises(RuntimeError, match="injected worker"):
            worker.expire_event(clean_engine, row.event_id, 1)
    finally:
        sql_event.remove(target, hook, fail)
    assert fired
    with Session(clean_engine) as db:
        assert db.get(Reservation, row.id).status == "HELD"
        assert db.get(Event, row.event_id).allocated_seats == 1
    assert_consistent(clean_engine)
    assert worker.expire_event(clean_engine, row.event_id, 1).expired == 1


@pytest.mark.parametrize("action", ["confirm", "cancel", "capacity", "close", "hold"])
def test_worker_first_serializes_api_operations(booking, clean_engine, monkeypatch, action):
    row = seed_reservation(clean_engine, booking, due=True)
    acquired, release = Signal(), Signal()
    pids = []
    original = worker.database_time

    def pause(db):
        pids.append(db.scalar(select(func.pg_backend_pid())))
        acquired.set()
        assert release.wait(10)
        return original(db)

    monkeypatch.setattr(worker, "database_time", pause)
    actor = booking["owner_session"]

    def api():
        if action in {"confirm", "cancel"}:
            return booking["execute"](action, row.id)
        if action == "hold":
            return booking["execute"]()
        with Session(clean_engine) as db:
            if action == "capacity":
                return event_service.change_capacity(
                    db, actor.cookie, actor.csrf_token, row.event_id, 1
                )
            return event_service.close_event(db, actor.cookie, actor.csrf_token, row.event_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        expiration = pool.submit(worker.expire_event, clean_engine, row.event_id, 10)
        try:
            assert acquired.wait(5)
            command = pool.submit(api)
            wait_until_blocked(clean_engine, pids[0])
        finally:
            release.set()
        assert expiration.result(timeout=5).expired == 1
        result = command.result(timeout=5)
    if action == "confirm":
        assert result.status == 409 and result.body["error"]["code"] == "HOLD_EXPIRED"
    elif action == "cancel":
        assert result.status == 200 and result.body["status"] == "EXPIRED"
    elif action == "hold":
        assert result.status == 201
    assert_consistent(clean_engine)


@pytest.mark.parametrize("action", ["confirm", "cancel", "capacity", "close", "hold"])
def test_api_first_worker_skip_then_stale_candidate_recheck(
    booking, clean_engine, monkeypatch, action
):
    row = seed_reservation(clean_engine, booking, due=action not in {"confirm", "cancel"})
    # Discovery is advisory: a candidate may have been observed before another transition.
    actor = booking["owner_session"]

    def api():
        if action in {"confirm", "cancel"}:
            return booking["execute"](action, row.id)
        if action == "hold":
            return booking["execute"]()
        with Session(clean_engine) as db:
            if action == "capacity":
                return event_service.change_capacity(
                    db, actor.cookie, actor.csrf_token, row.event_id, 1
                )
            return event_service.close_event(db, actor.cookie, actor.csrf_token, row.event_id)

    results = []
    from threading import get_ident, local

    state = local()
    caller_thread = get_ident()

    def after_lock(connection, cursor, statement, parameters, context, executemany):
        if (
            get_ident() == caller_thread
            and not getattr(state, "seen", False)
            and "FROM events" in statement
            and "FOR UPDATE" in statement
        ):
            state.seen = True
            with ThreadPoolExecutor(max_workers=1) as pool:
                results.append(
                    pool.submit(worker.expire_event, clean_engine, row.event_id, 10).result(
                        timeout=5
                    )
                )

    sql_event.listen(clean_engine, "after_cursor_execute", after_lock)
    try:
        api()
    finally:
        sql_event.remove(clean_engine, "after_cursor_execute", after_lock)
    assert results[0].skipped
    if action in {"confirm", "cancel"}:
        # The valid API transition won. Even a later post-deadline sweep is a no-op.
        monkeypatch.setattr(worker, "database_time", lambda db: row.hold_expires_at)
        with Session(clean_engine) as db:
            assert db.get(Reservation, row.id).status == (
                "CONFIRMED" if action == "confirm" else "CANCELLED"
            )
    again = worker.expire_event(clean_engine, row.event_id, 10)
    assert again.expired == int(action == "close")
    assert_consistent(clean_engine)


def test_worker_post_lock_clock_uses_actual_time(booking, clean_engine, monkeypatch):
    row = seed_reservation(clean_engine, booking)

    # Pause after the real event lock; set the stored deadline between xact_start and release.
    def after_lock(connection, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement and "FROM events" in statement:
            start, now = connection.execute(
                text("SELECT transaction_timestamp(), clock_timestamp()")
            ).one()
            deadline = start + (now - start) / 2
            assert start < deadline < now
            connection.execute(
                update(Reservation).where(Reservation.id == row.id).values(hold_expires_at=deadline)
            )

    sql_event.listen(clean_engine, "after_cursor_execute", after_lock)
    try:
        assert worker.expire_event(clean_engine, row.event_id, 1).expired == 1
    finally:
        sql_event.remove(clean_engine, "after_cursor_execute", after_lock)
    assert_consistent(clean_engine)


def test_expiration_indexes_support_bounded_scan_and_cleanup(clean_engine):
    indexes = {index["name"]: index for index in inspect(clean_engine).get_indexes("reservations")}
    assert indexes["ix_reservations_held_expiry"]["column_names"] == ["hold_expires_at", "event_id"]
    assert indexes["ix_reservations_event_held_expiry"]["column_names"] == [
        "event_id",
        "hold_expires_at",
        "id",
    ]
    with clean_engine.connect() as connection, connection.begin():
        connection.execute(text("SET LOCAL enable_seqscan=off"))
        plan = connection.scalar(
            text(
                "EXPLAIN (FORMAT JSON) SELECT id FROM reservations WHERE status='HELD' "
                "AND event_id=:id AND hold_expires_at<=clock_timestamp() "
                "ORDER BY hold_expires_at,id LIMIT 5"
            ),
            {"id": uuid4()},
        )
        assert "ix_reservations_event_held_expiry" in str(plan)
