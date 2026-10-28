"""Fixture state passes only through stdin/stdout captured by verify-local.ps1.

The orchestrator uses an isolated Compose project without host ports. No credentials
are written to evidence. Ordinary down/up retains this project's PostgreSQL volume.
"""

import argparse
import json
import secrets
import sys
from datetime import timedelta
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx2
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from csrs.auth.crypto import hash_password
from csrs.auth.service import database_time, issue_session
from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.models import Event, IdempotencyRecord, Reservation, SessionRecord, User


def client(settings, state):
    result = httpx2.Client(
        base_url="http://backend:8000",
        timeout=10,
        trust_env=False,
        headers={
            "Host": urlsplit(settings.public_origin).netloc,
            "Origin": settings.public_origin,
            "X-CSRF-Token": state["csrf"],
        },
    )
    result.cookies.set(settings.session_cookie_name, state["cookie"])
    return result


def prepare(engine, settings):
    scope = uuid4()
    with Session(engine, expire_on_commit=False) as db, db.begin():
        hashed = hash_password(secrets.token_urlsafe(32))
        users = [
            User(
                id=uuid4(),
                normalized_email=f"recovery-{scope.hex}-{i}@example.com",
                password_hash=hashed,
                role="ORGANIZER" if i == 0 else "ATTENDEE",
            )
            for i in range(3)
        ]
        db.add_all(users)
        db.flush()
        now = database_time(db)
        event = Event(
            id=scope,
            organizer_id=users[0].id,
            title="Isolated Phase 8 recovery",
            location="Disposable local Compose project",
            status="PUBLISHED",
            capacity=2,
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=2, hours=1),
            booking_closes_at=now + timedelta(days=1),
        )
        db.add(event)
        sessions = [issue_session(db, settings, user) for user in users[1:]]
        state = {
            "scope": str(scope),
            "users": [str(user.id) for user in users],
            "cookie": sessions[0].cookie,
            "csrf": sessions[0].csrf_token,
        }
    try:
        with client(settings, state) as http:
            held = http.post(
                f"/api/v1/events/{scope}/holds",
                json={},
                headers={"Idempotency-Key": "durable-hold"},
            )
            assert held.status_code == 201
            state["held"] = held.json()
            confirmed = http.post(
                f"/api/v1/reservations/{state['held']['id']}/confirm",
                json={},
                headers={"Idempotency-Key": "durable-confirm"},
            )
            assert confirmed.status_code == 200 and confirmed.json()["status"] == "CONFIRMED"
        # Worker is deliberately stopped by the orchestrator before this controlled deadline.
        with Session(engine) as db, db.begin():
            event = db.scalar(select(Event).where(Event.id == scope).with_for_update())
            now = database_time(db)
            db.add(
                Reservation(
                    event_id=scope,
                    user_id=users[2].id,
                    created_at=now - timedelta(minutes=10),
                    hold_expires_at=now - timedelta(seconds=1),
                )
            )
            event.allocated_seats += 1
        return state
    except Exception:
        cleanup(engine, state)
        raise


def verify(engine, settings, state):
    scope = UUID(state["scope"])
    with client(settings, state) as http:
        assert http.get("/api/v1/auth/me").status_code == 200
        replay = http.post(
            f"/api/v1/events/{scope}/holds", json={}, headers={"Idempotency-Key": "durable-hold"}
        )
        assert replay.status_code == 201 and replay.headers["Idempotency-Replayed"] == "true"
        assert replay.json() == state["held"]
        current = http.get(f"/api/v1/reservations/{state['held']['id']}")
        assert current.status_code == 200 and current.json()["status"] == "CONFIRMED"
    deadline = monotonic() + 60
    while True:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT e.allocated_seats, count(*) FILTER (WHERE r.status='EXPIRED') expired, "
                    "count(*) FILTER (WHERE r.status='CONFIRMED') confirmed, "
                    "count(*) FILTER (WHERE r.status IN ('HELD','CONFIRMED')) active "
                    "FROM events e JOIN reservations r ON e.id=r.event_id WHERE e.id=:id "
                    "GROUP BY e.allocated_seats"
                ),
                {"id": scope},
            ).one()
        assert row.allocated_seats == row.active and row.confirmed == 1
        if row.expired == 1:
            assert row.allocated_seats == 1
            break
        if monotonic() >= deadline:
            raise AssertionError("Worker did not recover overdue hold")
        sleep(0.1)
    return {
        "session_persisted": True,
        "exact_replay": True,
        "confirmed_preserved": 1,
        "worker_expired": 1,
        "allocated_seats": 1,
        "counter_matches": True,
    }


def cleanup(engine, state):
    scope = UUID(state["scope"])
    ids = [UUID(value) for value in state["users"]]
    with Session(engine) as db, db.begin():
        event = db.scalar(select(Event).where(Event.id == scope).with_for_update())
        owner = db.get(User, ids[0])
        assert owner.normalized_email == f"recovery-{scope.hex}-0@example.com"
        assert event.organizer_id == owner.id and event.title == "Isolated Phase 8 recovery"
        db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id.in_(ids)))
        db.execute(delete(Reservation).where(Reservation.event_id == scope))
        db.execute(delete(Event).where(Event.id == scope))
        db.execute(delete(SessionRecord).where(SessionRecord.user_id.in_(ids)))
        db.execute(delete(User).where(User.id.in_(ids)))
    return {"scoped_cleanup": True}


def database_outage(settings, state):
    with client(settings, state) as http:
        assert http.get("/api/v1/health/live").status_code == 200
        assert http.get("/api/v1/health/ready").status_code == 503
        reply = http.get(f"/api/v1/reservations/{state['held']['id']}")
        assert reply.status_code == 503
        assert reply.json()["error"]["code"] == "TEMPORARILY_UNAVAILABLE"
    return {"database_unavailable": True, "liveness": 200, "readiness": 503, "private_read": 503}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "verify", "cleanup", "database-outage"])
    action = parser.parse_args().action
    settings = Settings()
    if settings.environment != "local":
        parser.error("Requires local environment")
    engine = create_database_engine(settings)
    try:
        if action == "prepare":
            result = prepare(engine, settings)
        else:
            state = json.load(sys.stdin)
            if action == "verify":
                result = verify(engine, settings, state)
            elif action == "database-outage":
                result = database_outage(settings, state)
            else:
                result = cleanup(engine, state)
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
