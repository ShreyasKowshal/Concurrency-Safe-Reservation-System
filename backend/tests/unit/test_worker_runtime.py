import json
import logging
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import pytest
from pydantic import ValidationError

from csrs import worker
from csrs.config import Settings


@pytest.mark.parametrize(
    "field,value",
    [
        ("worker_poll_interval_seconds", 0),
        ("worker_poll_interval_seconds", float("inf")),
        ("worker_batch_size", 0),
        ("worker_batch_size", 1001),
        ("worker_retry_initial_seconds", 0),
        ("worker_retry_max_seconds", 301),
    ],
)
def test_worker_settings_are_bounded(settings, field, value):
    with pytest.raises(ValidationError):
        Settings(**(settings.model_dump() | {field: value}))


def test_worker_retry_range_validation(settings):
    with pytest.raises(ValidationError):
        Settings(
            **(
                settings.model_dump()
                | {
                    "worker_retry_initial_seconds": 10,
                    "worker_retry_max_seconds": 1,
                }
            )
        )


def test_retry_delay_is_bounded_and_does_not_overflow(settings):
    assert [worker.retry_delay(settings, n) for n in (1, 2, 3, 50, 100000)] == [1, 2, 4, 30, 30]


def test_structured_failure_logs_exclude_exception_and_settings(caplog):
    error = worker.OperationalError("secret SQL", {}, Exception("private DSN password"))
    with caplog.at_level(logging.INFO, logger="csrs.worker"):
        worker.database_failure("discovery_retry", error)
    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "discovery_retry" and payload["error_type"] == "OperationalError"
    assert "secret SQL" not in caplog.text and "private DSN" not in caplog.text


def test_already_stopped_worker_performs_no_database_work(settings, caplog):
    stop = Event()
    stop.set()
    with caplog.at_level(logging.INFO, logger="csrs.worker"):
        worker.run_worker(None, settings, stop)
    assert [json.loads(record.message)["event"] for record in caplog.records] == [
        "worker_started",
        "worker_stopped",
    ]


def test_failed_event_is_paced_without_starving_the_next_candidate(settings, monkeypatch, caplog):
    from uuid import uuid4

    first, second = uuid4(), uuid4()
    attempts, waits = [], []

    class Stop:
        def is_set(self):
            return len(waits) >= 2

        def wait(self, seconds):
            waits.append(seconds)

    monkeypatch.setattr(worker, "discover", lambda *args: worker.Page((first, second), None, 2))

    def expire(engine, identifier, batch_size):
        attempts.append(identifier)
        if identifier == first:
            raise worker.OperationalError("private SQL", {}, Exception("private connection"))
        return worker.Expiration(expired=1)

    monkeypatch.setattr(worker, "expire_event", expire)
    with caplog.at_level(logging.INFO, logger="csrs.worker"):
        worker.run_worker(None, settings, Stop())
    assert attempts == [first, second] and waits == [1, 1]
    cycle = next(
        json.loads(record.message)
        for record in caplog.records
        if '"event": "worker_cycle"' in record.message
    )
    assert cycle["failed"] == 1 and cycle["expired"] == 1


class StopAfter:
    def __init__(self, count):
        self.count = count
        self.waits = []

    def is_set(self):
        return len(self.waits) >= self.count

    def wait(self, seconds):
        self.waits.append(seconds)


def test_idle_worker_uses_normal_poll_interval(settings, monkeypatch):
    stop = StopAfter(1)
    monkeypatch.setattr(worker, "discover", lambda *args: worker.Page((), None, 0))
    worker.run_worker(None, settings, stop)
    assert stop.waits == [settings.worker_poll_interval_seconds]


def test_productive_pass_catches_up_after_equal_key_wrap(settings, monkeypatch):
    identifier = uuid4()
    position = worker.Position(datetime.now(UTC), datetime.now(UTC), identifier)
    pages = iter(
        [
            worker.Page((identifier,), position, settings.worker_batch_size),
            worker.Page((), None, 0),
            worker.Page((identifier,), None, 1),
        ]
    )
    seen_positions = []

    def discover(engine, batch_size, cursor):
        seen_positions.append(cursor)
        return next(pages)

    changes = iter([settings.worker_batch_size, 1])
    monkeypatch.setattr(worker, "discover", discover)
    monkeypatch.setattr(
        worker, "expire_event", lambda *args: worker.Expiration(expired=next(changes))
    )
    stop = StopAfter(3)
    worker.run_worker(None, settings, stop)
    assert seen_positions == [None, position, None]
    assert stop.waits == [worker.CATCHUP_DELAY_SECONDS] * 3


def test_busy_full_page_scans_ahead_to_later_event_without_spinning(settings, monkeypatch):
    busy, later = uuid4(), uuid4()
    position = worker.Position(datetime.now(UTC), datetime.now(UTC), busy)
    pages = iter(
        [
            worker.Page((busy,), position, settings.worker_batch_size),
            worker.Page((later,), None, 1),
            worker.Page((), None, 0),
        ]
    )
    attempts = []
    monkeypatch.setattr(worker, "discover", lambda *args: next(pages))

    def expire(engine, identifier, batch_size):
        attempts.append(identifier)
        return (
            worker.Expiration(skipped=True) if identifier == busy else worker.Expiration(expired=1)
        )

    monkeypatch.setattr(worker, "expire_event", expire)
    stop = StopAfter(3)
    worker.run_worker(None, settings, stop)
    assert attempts == [busy, later]
    assert stop.waits == [
        worker.SCAN_AHEAD_DELAY_SECONDS,
        worker.CATCHUP_DELAY_SECONDS,
        settings.worker_poll_interval_seconds,
    ]


def test_shutdown_during_catchup_does_not_scan_again(settings, monkeypatch):
    identifier = uuid4()
    calls = []

    def discover(*args):
        calls.append(True)
        return worker.Page((identifier,), None, 1)

    monkeypatch.setattr(worker, "discover", discover)
    monkeypatch.setattr(worker, "expire_event", lambda *args: worker.Expiration(expired=1))
    stop = StopAfter(1)
    worker.run_worker(None, settings, stop)
    assert calls == [True] and stop.waits == [worker.CATCHUP_DELAY_SECONDS]


def test_database_failures_back_off_then_resume_catchup(settings, monkeypatch):
    identifier = uuid4()
    attempts = []

    def discover(*args):
        attempts.append(True)
        if len(attempts) < 3:
            raise worker.OperationalError("private SQL", {}, Exception("private connection"))
        return worker.Page((identifier,), None, 1)

    monkeypatch.setattr(worker, "discover", discover)
    monkeypatch.setattr(worker, "expire_event", lambda *args: worker.Expiration(expired=1))
    stop = StopAfter(3)
    worker.run_worker(None, settings, stop)
    assert len(attempts) == 3
    assert stop.waits == [1, 2, worker.CATCHUP_DELAY_SECONDS]
