"""Local Compose restart/backlog smoke. Prepare while worker is stopped, verify after start.

docker compose exec -T backend python scripts/smoke_worker.py prepare
docker compose --profile worker up -d worker
docker compose exec -T backend python scripts/smoke_worker.py verify RUN_UUID
"""

import argparse
import json
import secrets
from datetime import timedelta
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx2
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from csrs.auth.crypto import hash_password
from csrs.auth.service import database_time
from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.models import Event, IdempotencyRecord, Reservation, SessionRecord, User


def prepare(engine):
    run_id = uuid4()
    with Session(engine) as db, db.begin():
        now = database_time(db)
        hashed = hash_password(secrets.token_urlsafe(32))
        users = [
            User(
                id=uuid4(),
                normalized_email=f"phase5-{run_id.hex}-{i}@example.com",
                password_hash=hashed,
                role="ORGANIZER" if i == 0 else "ATTENDEE",
            )
            for i in range(6)
        ]
        db.add_all(users)
        db.flush()
        event = Event(
            id=run_id,
            organizer_id=users[0].id,
            title="Temporary Phase 5 smoke",
            location="Local verification",
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=2, hours=1),
            booking_closes_at=now + timedelta(days=1),
            status="PUBLISHED",
            capacity=5,
            allocated_seats=5,
        )
        db.add(event)
        db.flush()
        db.add_all(
            [
                Reservation(
                    event_id=run_id,
                    user_id=user.id,
                    status="HELD",
                    created_at=now - timedelta(minutes=10),
                    hold_expires_at=now - timedelta(minutes=1),
                )
                for user in users[1:]
            ]
        )
    print(run_id)


def verify(engine, run_id, public_origin):
    with Session(engine) as db:
        event = db.get(Event, run_id)
        if event is None or event.title != "Temporary Phase 5 smoke":
            raise ValueError("Unknown smoke scenario")
        owner = db.get(User, event.organizer_id)
        if owner.normalized_email != f"phase5-{run_id.hex}-0@example.com":
            raise ValueError("Scenario ownership mismatch")
        ids = list(
            db.scalars(
                select(User.id).where(
                    User.normalized_email.in_(
                        [f"phase5-{run_id.hex}-{i}@example.com" for i in range(6)]
                    )
                )
            )
        )
    try:
        deadline = monotonic() + 60
        while True:
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT e.allocated_seats, "
                        "count(*) FILTER (WHERE r.status='EXPIRED') AS expired, "
                        "count(*) FILTER (WHERE r.status IN ('HELD','CONFIRMED')) AS active "
                        "FROM events e JOIN reservations r ON r.event_id=e.id WHERE e.id=:id "
                        "GROUP BY e.allocated_seats"
                    ),
                    {"id": run_id},
                ).one()
                assert row.allocated_seats == row.active
            if row.expired == 5:
                assert row.allocated_seats == 0
                break
            if monotonic() >= deadline:
                raise RuntimeError("Worker did not drain the generated backlog")
            sleep(0.1)  # Observe committed database progress; never establish a race ordering.
        with httpx2.Client(
            timeout=10, trust_env=False, headers={"Host": urlsplit(public_origin).netloc}
        ) as client:
            assert client.get("http://backend:8000/api/v1/health/ready").status_code == 200
            assert client.get("http://frontend:5173/api/v1/health/ready").status_code == 200
            reply = client.get(f"http://backend:8000/api/v1/events/{run_id}/availability")
            assert reply.status_code == 200 and reply.json()["available_seats"] == 5
        print(
            json.dumps(
                {
                    "event": "worker_smoke_passed",
                    "expired": 5,
                    "allocated_seats": 0,
                    "http_checks": 3,
                }
            )
        )
    finally:
        with Session(engine) as db, db.begin():
            db.scalar(select(Event).where(Event.id == run_id).with_for_update())
            db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id.in_(ids)))
            db.execute(delete(Reservation).where(Reservation.event_id == run_id))
            db.execute(delete(Event).where(Event.id == run_id))
            db.execute(delete(SessionRecord).where(SessionRecord.user_id.in_(ids)))
            db.execute(delete(User).where(User.id.in_(ids)))
        print(json.dumps({"event": "worker_smoke_cleanup", "users": len(ids), "events": 1}))


def main():
    parser = argparse.ArgumentParser(description="Local Phase 5 worker smoke")
    parser.add_argument("action", choices=["prepare", "verify"])
    parser.add_argument("run_id", nargs="?", type=UUID)
    args = parser.parse_args()
    settings = Settings()
    if settings.environment != "local":
        parser.error("Requires local environment")
    if args.action == "verify" and args.run_id is None:
        parser.error("verify requires the UUID returned by prepare")
    engine = create_database_engine(settings)
    try:
        if args.action == "prepare":
            prepare(engine)
        else:
            verify(engine, args.run_id, settings.public_origin)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
