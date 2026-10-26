"""Independent CLI workers, real crashes, restart, and isolated PostgreSQL connection outages."""

import json
import os
import re
import signal
import subprocess
import sys
from contextlib import contextmanager
from queue import Empty, Queue
from threading import Thread
from time import monotonic

import pytest
from sqlalchemy import create_engine, func, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from test_reservations import assert_consistent

from csrs.models import Event, Reservation

pytestmark = pytest.mark.integration

GATED = """
import json
from csrs import worker
original = worker.discover
first = True
def discover(*args, **kwargs):
    global first
    page = original(*args, **kwargs)
    if first:
        first = False
        print(json.dumps({"event":"candidates_ready","scanned":page.scanned}), flush=True)
        input()
    return page
worker.discover = discover
worker.main()
"""
BEFORE_COMMIT = """
import json
from threading import Event
from csrs import worker
original = worker.expire_due_holds
def pause(*args, **kwargs):
    changed = original(*args, **kwargs)
    args[0].flush()
    print(json.dumps({"event":"before_commit"}), flush=True)
    Event().wait(30)
    return changed
worker.expire_due_holds = pause
worker.main()
"""
AFTER_COMMIT = """
import json, os
from csrs import worker
original = worker.expire_event
def crash(*args, **kwargs):
    result = original(*args, **kwargs)
    print(json.dumps({"event":"after_commit"}), flush=True)
    os._exit(23)
worker.expire_event = crash
worker.main()
"""


class Process:
    def __init__(self, settings, code=None, **changes):
        environment = os.environ.copy()
        for field, value in (
            settings.model_dump()
            | {
                "worker_poll_interval_seconds": 0.05,
                "worker_batch_size": 2,
                "worker_retry_initial_seconds": 0.05,
                "worker_retry_max_seconds": 0.2,
            }
            | changes
        ).items():
            environment["CSRS_" + field.upper()] = str(
                value.get_secret_value() if hasattr(value, "get_secret_value") else value
            )
        args = (
            [sys.executable, "-u", "-c", code]
            if code
            else [sys.executable, "-u", "-m", "csrs.worker"]
        )
        self.process = subprocess.Popen(
            args,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.queue = Queue()
        self.logs = []

        def read():
            for line in self.process.stdout:
                self.logs.append(line)
                try:
                    self.queue.put(json.loads(line))
                except ValueError:
                    pass

        self.reader = Thread(target=read, daemon=True)
        self.reader.start()

    def wait(self, event, predicate=lambda record: True, timeout=10):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            try:
                record = self.queue.get(timeout=max(0.01, deadline - monotonic()))
                if record.get("event") == event and predicate(record):
                    return record
            except Empty:
                break
        pytest.fail(
            f"No {event} log from worker; exit={self.process.poll()}, logs={self.logs[-8:]}"
        )

    def release(self):
        self.process.stdin.write("continue\n")
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()


@contextmanager
def running(settings, code=None, **changes):
    process = Process(settings, code, **changes)
    try:
        process.wait("worker_started")
        yield process
    finally:
        process.close()


def count_active(engine, identifier):
    with Session(engine) as db:
        return db.get(Event, identifier).allocated_seats


def test_worker_recovers_from_real_statement_timeout(
    held_event_factory, clean_engine, postgres_settings
):
    event, _ = held_event_factory(1)
    with clean_engine.begin() as holder:
        holder.execute(text("LOCK TABLE reservations IN ACCESS EXCLUSIVE MODE"))
        process = Process(postgres_settings, db_statement_timeout_ms=100)
        try:
            process.wait("worker_started")
            retry = process.wait("discovery_retry")
            assert retry["sqlstate"] == "57014"
            process.wait("worker_backoff")
        except BaseException:
            process.close()
            raise
    try:
        process.wait("worker_cycle", lambda record: record["expired"] == 1)
        assert count_active(clean_engine, event.id) == 0
    finally:
        process.close()
    assert_consistent(clean_engine)


def test_cli_drains_bounded_backlog_without_http(
    held_event_factory, clean_engine, postgres_settings
):
    event, _ = held_event_factory(17)
    with running(postgres_settings) as process:
        changed = 0
        cycles = 0
        while changed < 17:
            record = process.wait("worker_cycle")
            assert record["scanned"] <= 2 and record["expired"] <= 2
            changed += record["expired"]
            cycles += 1
            assert cycles < 40
        assert count_active(clean_engine, event.id) == 0
        process.process.terminate()
        assert process.process.wait(timeout=5) == 0
        process.wait("worker_stopped")
    assert_consistent(clean_engine)


def test_cli_catches_up_multiple_batches_with_identical_deadlines(
    held_event_factory, clean_engine, postgres_settings
):
    event, rows = held_event_factory(5)
    assert len({row.hold_expires_at for row in rows}) == 1
    with running(postgres_settings, worker_poll_interval_seconds=60) as process:
        cycles = []
        while sum(record["expired"] for record in cycles) < 5:
            cycles.append(process.wait("worker_cycle", timeout=5))
        assert [record["expired"] for record in cycles] == [2, 0, 2, 0, 1]
        assert all(record["next_delay_seconds"] == 0.25 for record in cycles)
        assert count_active(clean_engine, event.id) == 0
    assert_consistent(clean_engine)


def test_two_processes_with_identical_candidate_pages(
    held_event_factory, clean_engine, postgres_settings
):
    event, _ = held_event_factory(2)
    with running(postgres_settings, GATED) as first, running(postgres_settings, GATED) as second:
        assert first.wait("candidates_ready")["scanned"] == 2
        assert second.wait("candidates_ready")["scanned"] == 2
        first.release()
        second.release()
        records = [first.wait("worker_cycle"), second.wait("worker_cycle")]
        assert sum(record["expired"] for record in records) == 2
        assert count_active(clean_engine, event.id) == 0
    assert_consistent(clean_engine)


def test_independent_process_skips_event_held_by_another_worker(
    held_event_factory, clean_engine, postgres_settings
):
    event, _ = held_event_factory(1)
    paused = BEFORE_COMMIT.replace("Event().wait(30)", "input()")
    with running(postgres_settings, paused, worker_poll_interval_seconds=60) as first:
        first.wait("before_commit")
        try:
            with running(postgres_settings, GATED, worker_poll_interval_seconds=60) as second:
                assert second.wait("candidates_ready")["scanned"] == 1
                second.release()
                # The first worker still owns the event row, so a blocking SELECT cannot pass.
                cycle = second.wait("worker_cycle", timeout=5)
                assert cycle["skipped"] == 1 and cycle["expired"] == cycle["failed"] == 0
                assert cycle["next_delay_seconds"] == 60
                assert first.process.poll() is None
                assert count_active(clean_engine, event.id) == 1
                first.release()
                assert (
                    first.wait("worker_cycle", lambda record: record["expired"] == 1)["expired"]
                    == 1
                )
                assert count_active(clean_engine, event.id) == 0
        finally:
            if first.process.poll() is None:
                first.release()
    assert_consistent(clean_engine)


def test_sigterm_finishes_active_transaction_before_exit(
    held_event_factory, clean_engine, postgres_settings
):
    event, _ = held_event_factory(1)
    with running(
        postgres_settings, BEFORE_COMMIT.replace("Event().wait(30)", "input()")
    ) as process:
        process.wait("before_commit")
        process.process.terminate()
        process.release()
        assert process.process.wait(timeout=5) == 0
        process.wait("worker_stopped")
    assert count_active(clean_engine, event.id) == 0
    assert_consistent(clean_engine)


@pytest.mark.parametrize(
    "code,marker,expected", [(BEFORE_COMMIT, "before_commit", 1), (AFTER_COMMIT, "after_commit", 0)]
)
def test_real_process_crash_and_restart(
    held_event_factory, clean_engine, postgres_settings, code, marker, expected
):
    event, rows = held_event_factory(1)
    with running(postgres_settings, code) as process:
        process.wait(marker)
        if marker == "before_commit":
            process.process.kill()
            process.process.wait(timeout=5)
        else:
            assert process.process.wait(timeout=5) == 23
    assert count_active(clean_engine, event.id) == expected
    assert_consistent(clean_engine)
    with running(postgres_settings) as restarted:
        restarted.wait("worker_cycle")
        assert count_active(clean_engine, event.id) == 0
    assert_consistent(clean_engine)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_graceful_idle_shutdown_then_restart(
    held_event_factory, clean_engine, postgres_settings, signum
):
    event, rows = held_event_factory(1, due=False)
    with running(postgres_settings, worker_poll_interval_seconds=60) as process:
        process.wait("worker_cycle")
        process.process.send_signal(signum)
        assert process.process.wait(timeout=5) == 0
        process.wait("worker_stopped")
    with clean_engine.begin() as connection:
        connection.execute(
            update(Reservation)
            .where(Reservation.id == rows[0].id)
            .values(hold_expires_at=func.clock_timestamp())
        )
    assert count_active(clean_engine, event.id) == 1
    with running(postgres_settings) as restarted:
        restarted.wait("worker_cycle", lambda record: record["expired"] == 1)
    assert_consistent(clean_engine)


@pytest.mark.parametrize("startup", [True, False])
def test_real_database_connection_outage_and_recovery(
    held_event_factory, clean_engine, postgres_settings, startup
):
    event, rows = held_event_factory(1, due=startup)
    name = clean_engine.url.database
    assert re.fullmatch(r"csrs_phase2_[0-9a-f]{32}_test", name)
    input_url = make_url(os.environ["CSRS_TEST_DATABASE_URL"])
    admin = create_engine(input_url, isolation_level="AUTOCOMMIT")
    process = None
    try:
        if not startup:
            process = Process(postgres_settings, GATED)
            process.wait("worker_started")
            process.wait("candidates_ready")
            with clean_engine.begin() as connection:
                connection.execute(
                    update(Reservation)
                    .where(Reservation.id == rows[0].id)
                    .values(hold_expires_at=func.clock_timestamp())
                )
        clean_engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS false')
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"),
                {"name": name},
            )
        if startup:
            process = Process(postgres_settings)
            process.wait("worker_started")
        else:
            process.release()
        process.wait("discovery_retry")
        backoff = process.wait("worker_backoff")
        assert 0.05 <= backoff["delay_seconds"] <= 0.2
        assert process.process.poll() is None
        with admin.connect() as connection:
            connection.exec_driver_sql(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS true')
        process.wait("worker_cycle", lambda record: record["expired"] == 1)
        assert count_active(clean_engine, event.id) == 0
        assert "postgresql" not in "".join(process.logs) and "csrs_test_local_only" not in "".join(
            process.logs
        )
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS true')
        if process:
            process.close()
        admin.dispose()
    assert_consistent(clean_engine)
