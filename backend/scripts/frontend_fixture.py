"""Local browser-test fixtures. No HTTP endpoint or production clock override.

Only UUID-scoped accounts/events are created, adjusted, reconciled, and removed.
Run inside the configured local backend container; never against a shared deployment.
"""

import json
import sys
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from csrs.auth.crypto import hash_password, token_digest, valid_token
from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.models import Event, IdempotencyRecord, Reservation, Role, SessionRecord, User
from csrs.reservations.service import database_time


def run(action: str, scope: str, cookies: list[str]):
    # Validate before constructing any cleanup selector.
    scope = UUID(scope).hex
    settings = Settings()
    if settings.environment != "local":
        raise SystemExit("Browser fixture requires the local development environment")
    emails = {name: f"e2e-{scope}-{name}@example.com" for name in ("owner", "attendee", "rival")}
    engine = create_database_engine(settings)
    try:
        with Session(engine, expire_on_commit=False) as db, db.begin():
            users = select(User.id).where(User.normalized_email.in_(list(emails.values())))
            events = select(Event.id).where(Event.organizer_id.in_(users))
            if action == "prepare":
                before = {
                    model.__tablename__: db.scalar(select(func.count()).select_from(model))
                    for model in (User, SessionRecord, Event, Reservation, IdempotencyRecord)
                }
                password = f"Browser fixture {scope}!"
                hashed = hash_password(password)
                owner = User(
                    normalized_email=emails["owner"], password_hash=hashed, role=Role.ORGANIZER
                )
                rival = User(
                    normalized_email=emails["rival"], password_hash=hashed, role=Role.ATTENDEE
                )
                db.add_all([owner, rival])
                db.flush()
                now = database_time(db)
                result = {}
                for name in ("experience", "final", "expiry", "recovery"):
                    event = Event(
                        organizer_id=owner.id,
                        title=f"E2E {name} {scope[:8]}",
                        description="A real PostgreSQL-backed browser test event.",
                        location="CSRS browser lab",
                        status="PUBLISHED",
                        capacity=1 if name == "final" else 10,
                        starts_at=now + timedelta(days=2),
                        ends_at=now + timedelta(days=2, hours=1),
                        booking_closes_at=now + timedelta(days=1),
                    )
                    db.add(event)
                    db.flush()
                    result[name] = str(event.id)
                return {"emails": emails, "password": password, "events": result, "before": before}
            if action == "expire":
                event = db.scalar(
                    select(Event)
                    .where(Event.organizer_id.in_(users), Event.title == f"E2E expiry {scope[:8]}")
                    .with_for_update()
                )
                if event is None:
                    raise ValueError("Missing scoped expiry event")
                now = database_time(db)
                for row in db.scalars(
                    select(Reservation).where(
                        Reservation.event_id == event.id, Reservation.status == "HELD"
                    )
                ):
                    row.created_at = now - timedelta(minutes=10)
                    row.hold_expires_at = now - timedelta(seconds=1)
                return {"expiry_adjusted": True}
            if action == "verify":
                active = (
                    select(func.count())
                    .select_from(Reservation)
                    .where(
                        Reservation.event_id == Event.id,
                        Reservation.status.in_(["HELD", "CONFIRMED"]),
                    )
                    .correlate(Event)
                    .scalar_subquery()
                )
                invalid = db.scalar(
                    select(func.count())
                    .select_from(Event)
                    .where(
                        Event.id.in_(events),
                        (Event.allocated_seats != active)
                        | (Event.allocated_seats < 0)
                        | (Event.allocated_seats > Event.capacity),
                    )
                )
                duplicates = db.execute(
                    select(Reservation.user_id, Reservation.event_id)
                    .where(
                        Reservation.event_id.in_(events),
                        Reservation.status.in_(["HELD", "CONFIRMED"]),
                    )
                    .group_by(Reservation.user_id, Reservation.event_id)
                    .having(func.count() > 1)
                ).all()
                final = db.scalar(
                    select(Event).where(
                        Event.id.in_(events), Event.title == f"E2E final {scope[:8]}"
                    )
                )
                assert invalid == 0 and duplicates == [] and final.allocated_seats == 1
                return {
                    "counter_invariants": True,
                    "active_uniqueness": True,
                    "final_seat_allocated": 1,
                }
            if action == "cleanup":
                # Serialize with the worker before touching reservation rows.
                list(
                    db.scalars(
                        select(Event)
                        .where(Event.id.in_(events))
                        .order_by(Event.id)
                        .with_for_update()
                    )
                )
                db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id.in_(users)))
                db.execute(delete(Reservation).where(Reservation.event_id.in_(events)))
                db.execute(delete(Event).where(Event.organizer_id.in_(users)))
                db.execute(delete(SessionRecord).where(SessionRecord.user_id.in_(users)))
                # Remove only anonymous pre-sessions whose cookies the test's own
                # browser contexts supplied through stdin (never logs/files/URLs).
                hashes = [token_digest(cookie) for cookie in cookies if valid_token(cookie)]
                if hashes:
                    db.execute(
                        delete(SessionRecord).where(
                            SessionRecord.user_id.is_(None), SessionRecord.token_hash.in_(hashes)
                        )
                    )
                db.execute(delete(User).where(User.normalized_email.in_(list(emails.values()))))
                db.flush()
                after = {
                    model.__tablename__: db.scalar(select(func.count()).select_from(model))
                    for model in (User, SessionRecord, Event, Reservation, IdempotencyRecord)
                }
                return {"scoped_cleanup": True, "after": after}
            raise ValueError("Unknown fixture operation")
    finally:
        engine.dispose()


if __name__ == "__main__":
    cookies = json.load(sys.stdin) if sys.argv[1] == "cleanup" else []
    print(json.dumps(run(*sys.argv[1:], cookies)))
