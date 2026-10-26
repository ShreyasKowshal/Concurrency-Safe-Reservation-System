"""Standalone PostgreSQL expiration worker. No HTTP, Redis, or durable process-local work."""

import argparse
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event as StopEvent
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Engine, literal_column, select, tuple_
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError
from sqlalchemy.orm import Session

from csrs.auth.service import database_time
from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.models import Event, Reservation
from csrs.reservations.transitions import expire_due_holds

LOGGER = logging.getLogger("csrs.worker")
RECOVERABLE = (OperationalError, InterfaceError, DatabaseTimeoutError)
CATCHUP_DELAY_SECONDS = 0.25
SCAN_AHEAD_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class Position:
    cutoff: datetime
    deadline: datetime
    event_id: UUID


@dataclass(frozen=True)
class Page:
    event_ids: tuple[UUID, ...]
    position: Position | None
    scanned: int


@dataclass(frozen=True)
class Expiration:
    expired: int = 0
    skipped: bool = False


def discover(engine: Engine, batch_size: int, position: Position | None = None) -> Page:
    """Read at most batch_size index entries, without acquiring reservation locks.

    A fixed cutoff bounds each pass even as new holds become due. The cursor skips entire
    equal (deadline,event) groups: omitted duplicates still belong to an already seen event
    and are reconsidered on wrap. This position is only navigation, never ownership/work state.
    """
    with Session(engine) as db, db.begin():
        cutoff = position.cutoff if position else database_time(db)
        statement = select(Reservation.hold_expires_at, Reservation.event_id).where(
            Reservation.status == literal_column("'HELD'"),
            Reservation.hold_expires_at <= cutoff,
        )
        if position:
            statement = statement.where(
                tuple_(Reservation.hold_expires_at, Reservation.event_id)
                > tuple_(position.deadline, position.event_id)
            )
        rows = list(
            db.execute(
                statement.order_by(
                    Reservation.hold_expires_at,
                    Reservation.event_id,
                ).limit(batch_size)
            )
        )
        next_position = Position(cutoff, *rows[-1]) if len(rows) == batch_size else None
        return Page(tuple(dict.fromkeys(row.event_id for row in rows)), next_position, len(rows))


def expire_event(engine: Engine, event_id: UUID, batch_size: int) -> Expiration:
    """One event, one explicit transaction. Busy/missing events are deferred, not waited on."""
    with Session(engine, expire_on_commit=False) as db, db.begin():
        event = db.scalar(
            select(Event)
            .where(Event.id == event_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if event is None:
            return Expiration(skipped=True)
        now = database_time(db)
        changed = expire_due_holds(db, event, now, limit=batch_size)
        db.flush()
    return Expiration(expired=changed)


def emit(event: str, *, level: int = logging.INFO, **fields) -> None:
    LOGGER.log(
        level,
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": event,
                "pid": os.getpid(),
                **fields,
            },
            sort_keys=True,
        ),
    )


def database_failure(event: str, error: Exception, **fields) -> None:
    # SQLAlchemy exception strings can contain SQL/DSNs; log only class and SQLSTATE.
    emit(
        event,
        level=logging.WARNING,
        error_type=type(error).__name__,
        sqlstate=getattr(getattr(error, "orig", None), "sqlstate", None),
        **fields,
    )


def retry_delay(settings: Settings, failures: int) -> float:
    return min(
        settings.worker_retry_max_seconds,
        settings.worker_retry_initial_seconds * 2 ** min(max(failures - 1, 0), 16),
    )


def run_worker(engine: Engine, settings: Settings, stop: StopEvent) -> None:
    position = None
    pass_had_progress = False
    failures = 0
    emit(
        "worker_started",
        batch_size=settings.worker_batch_size,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
    )
    try:
        while not stop.is_set():
            failed = 0
            expired = skipped = processed = 0
            try:
                previous_position = position
                page = discover(engine, settings.worker_batch_size, position)
                position = page.position
                for event_id in page.event_ids:
                    if stop.is_set():
                        break
                    try:
                        result = expire_event(engine, event_id, settings.worker_batch_size)
                        expired += result.expired
                        skipped += result.skipped
                        processed += 1
                    except RECOVERABLE as error:
                        failed += 1
                        database_failure(
                            "event_expiration_retry",
                            error,
                            event_id=str(event_id),
                            retry_delay_seconds=settings.worker_retry_initial_seconds,
                        )
                        # A cached page can contain many events when PostgreSQL goes down.
                        # Pace failures within the page as well as between cycles.
                        stop.wait(settings.worker_retry_initial_seconds)
                pass_had_progress = pass_had_progress or expired > 0
                productive_wrap = (
                    previous_position is not None and position is None and pass_had_progress
                )
                if position is None:
                    pass_had_progress = False
                failures = failures + 1 if failed else 0
                if failed:
                    delay = retry_delay(settings, failures)
                elif expired or productive_wrap:
                    # Drain known work promptly, including equal-key rows skipped until wrap.
                    delay = min(settings.worker_poll_interval_seconds, CATCHUP_DELAY_SECONDS)
                elif position is not None:
                    # Advance past a full busy/stale page without spinning on one locked event.
                    delay = min(settings.worker_poll_interval_seconds, SCAN_AHEAD_DELAY_SECONDS)
                else:
                    delay = settings.worker_poll_interval_seconds
                emit(
                    "worker_cycle",
                    scanned=page.scanned,
                    processed=processed,
                    expired=expired,
                    skipped=skipped,
                    failed=failed,
                    pass_complete=position is None,
                    next_delay_seconds=delay,
                )
            except RECOVERABLE as error:
                failed = 1
                position = None
                pass_had_progress = False
                database_failure("discovery_retry", error)
                failures += 1
                delay = retry_delay(settings, failures)
            if failed:
                emit("worker_backoff", delay_seconds=delay)
            stop.wait(delay)
    finally:
        emit("worker_stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="CSRS reservation expiration worker")
    parser.add_argument("--env-file", help="Optional explicit environment file")
    args = parser.parse_args()
    try:
        settings = Settings(_env_file=args.env_file)
    except ValidationError:
        parser.error("Invalid CSRS worker configuration.")
    logging.basicConfig(level=settings.log_level.upper(), format="%(message)s", stream=sys.stdout)
    stop = StopEvent()
    previous = {}
    engine = create_database_engine(settings)
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_: stop.set())
        run_worker(engine, settings, stop)
    except Exception as error:
        emit("worker_failed", level=logging.ERROR, error_type=type(error).__name__)
        raise SystemExit(1) from None
    finally:
        engine.dispose()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    main()
