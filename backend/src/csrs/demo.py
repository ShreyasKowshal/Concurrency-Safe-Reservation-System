"""Explicit local-only interview fixtures with deterministic UUID ownership boundaries."""

import argparse
import getpass
import json
from datetime import timedelta
from uuid import UUID, uuid5

from sqlalchemy import Engine, delete, func, or_, select, text
from sqlalchemy.orm import Session

from csrs.auth.crypto import hash_password
from csrs.auth.service import database_time
from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.models import Event, IdempotencyRecord, Reservation, SessionRecord, User

NAMES = ("organizer", "attendee", "rival")
EVENTS = (("workshop", 20, "PUBLISHED"), ("final-seat", 1, "PUBLISHED"), ("draft", 10, "DRAFT"))


def identities(scope: UUID) -> dict[str, UUID]:
    return {name: uuid5(scope, f"csrs-demo-user:{name}") for name in NAMES}


def email(scope: UUID, name: str) -> str:
    return f"demo-{scope.hex}-{name}@example.com"


def operate(engine: Engine, scope: UUID, action: str, password: str | None = None) -> dict:
    ids = identities(scope)
    event_ids = {name: uuid5(scope, f"csrs-demo-event:{name}") for name, _, _ in EVENTS}
    hashed = hash_password(password) if password is not None else None
    with Session(engine) as db, db.begin():
        # Serializes repeated setup/cleanup for this scope, including first creation.
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": scope.int % (2**63)})
        users = list(
            db.scalars(
                select(User).where(
                    or_(
                        User.id.in_(ids.values()),
                        User.normalized_email.in_([email(scope, name) for name in NAMES]),
                    )
                )
            )
        )
        expected = {value: email(scope, name) for name, value in ids.items()}
        if any(expected.get(user.id) != user.normalized_email for user in users):
            raise ValueError("Demo identity collision; refusing to modify existing accounts")
        events = list(
            db.scalars(
                select(Event)
                .where(or_(Event.id.in_(event_ids.values()), Event.organizer_id.in_(ids.values())))
                .order_by(Event.id)
                .with_for_update()
            )
        )
        if any(event.organizer_id != ids["organizer"] for event in events):
            raise ValueError("Demo event ownership collision")
        if action == "prepare":
            if not users:
                if hashed is None:
                    raise ValueError("New demo scope requires a private password")
                for name, user_id in ids.items():
                    db.add(
                        User(
                            id=user_id,
                            normalized_email=email(scope, name),
                            password_hash=hashed,
                            role="ORGANIZER" if name == "organizer" else "ATTENDEE",
                        )
                    )
                db.flush()
                now = database_time(db)
                for name, capacity, status in EVENTS:
                    db.add(
                        Event(
                            id=event_ids[name],
                            organizer_id=ids["organizer"],
                            title=f"CSRS demo: {name.replace('-', ' ')}",
                            description="Interview demonstration. PostgreSQL owns capacity.",
                            location="Local interview lab",
                            starts_at=now + timedelta(days=7),
                            ends_at=now + timedelta(days=7, hours=2),
                            booking_closes_at=now + timedelta(days=6),
                            status=status,
                            capacity=capacity,
                        )
                    )
            elif len(users) != len(NAMES):
                raise ValueError("Incomplete demo scope; inspect before cleanup/recreation")
            # Existing scopes preserve passwords, schedules, bookings and edited events.
        elif action == "cleanup":
            owned = [event.id for event in events]
            foreign = db.scalar(
                select(func.count())
                .select_from(Reservation)
                .where(
                    or_(
                        Reservation.event_id.in_(owned) & Reservation.user_id.not_in(ids.values()),
                        Reservation.user_id.in_(ids.values()) & Reservation.event_id.not_in(owned),
                    )
                )
            )
            if foreign:
                raise ValueError(
                    "Scope has reservations involving other accounts/events; refusing cleanup"
                )
            db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id.in_(ids.values())))
            db.execute(delete(Reservation).where(Reservation.event_id.in_(owned)))
            db.execute(delete(Event).where(Event.id.in_(owned)))
            db.execute(delete(SessionRecord).where(SessionRecord.user_id.in_(ids.values())))
            db.execute(delete(User).where(User.id.in_(ids.values())))
            return {"scope": str(scope), "scoped_cleanup": True, "events_removed": len(owned)}
        elif action != "status":
            raise ValueError("Unknown demo action")
        return {
            "scope": str(scope),
            "accounts": {name: email(scope, name) for name in NAMES},
            "events": {name: str(value) for name, value in event_ids.items()},
            "existing_accounts": len(users) if users else (3 if action == "prepare" else 0),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit local interview demo setup/cleanup")
    parser.add_argument("action", choices=["prepare", "status", "cleanup"])
    parser.add_argument("--scope", required=True, type=UUID, help="Your recorded demo UUID")
    args = parser.parse_args()
    engine = None
    try:
        settings = Settings()
        if settings.environment != "local":
            parser.error("Demo fixtures require CSRS_ENVIRONMENT=local")
        engine = create_database_engine(settings)
        password = None
        if args.action == "prepare":
            with Session(engine) as db:
                exists = db.scalar(
                    select(User.id).where(User.id.in_(identities(args.scope).values()))
                )
            if exists is None:
                password = getpass.getpass("New local demo password (15-128 characters): ")
                if not 15 <= len(password) <= 128:
                    parser.error("Password must contain 15-128 characters")
                if password != getpass.getpass("Repeat demo password: "):
                    parser.error("Passwords do not match")
        print(json.dumps(operate(engine, args.scope, args.action, password), indent=2))
        return 0
    except ValueError as error:
        # These are our controlled fixture guards, not driver/SQL errors.
        print(str(error))
        return 1
    except Exception as error:
        print(json.dumps({"event": "demo_failed", "error_class": type(error).__name__}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
