"""Live local API/Redis/worker smoke; scoped records, no credentials in output.

Run available, outage, and recovered around an external Compose Redis stop/start.
The worker must be running; restart the API while Redis is stopped to test cold startup.
"""

import argparse
import json
import secrets
from datetime import timedelta
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from csrs.auth.crypto import hash_password, token_digest
from csrs.auth.service import database_time, issue_session
from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.models import Event, IdempotencyRecord, Reservation, SessionRecord, User
from csrs.redis_support import RedisSupport


def reconcile(engine):
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("""
            SELECT count(*) FROM events e WHERE allocated_seats < 0
            OR allocated_seats > capacity OR allocated_seats != (
                SELECT count(*) FROM reservations r WHERE r.event_id=e.id
                AND r.status IN ('HELD','CONFIRMED'))
        """)
            )
            == 0
        )
        assert (
            connection.scalar(
                text("""
            SELECT count(*) FROM (SELECT user_id,event_id FROM reservations
            WHERE status IN ('HELD','CONFIRMED') GROUP BY user_id,event_id
            HAVING count(*) > 1) duplicates
        """)
            )
            == 0
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.completed_at.is_(None))
            )
            == 0
        )


def main():
    parser = argparse.ArgumentParser(description="Local Phase 6 supporting Redis smoke")
    parser.add_argument("mode", choices=["available", "outage", "recovered"])
    mode = parser.parse_args().mode
    settings = Settings()
    if (
        settings.environment != "local"
        or not settings.rate_limits_enabled
        or not settings.metadata_cache_enabled
    ):
        parser.error("Requires local environment with Phase 6 features enabled")
    engine, support = create_database_engine(settings), RedisSupport(settings)
    run_id = uuid4()
    user_ids, digests, results = [], set(), []
    tables = (User, SessionRecord, Event, Reservation, IdempotencyRecord)

    def counts():
        with Session(engine) as db:
            return {
                model.__tablename__: db.scalar(select(func.count()).select_from(model))
                for model in tables
            }

    before = counts()
    client = httpx2.Client(
        base_url="http://backend:8000",
        timeout=10,
        trust_env=False,
        headers={"Host": urlsplit(settings.public_origin).netloc},
    )

    def check(label, method, path, expected, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected, (label, response.status_code)
        results.append(label)
        return response

    try:
        if mode == "outage":
            try:
                support.client.ping()
            except RedisError:
                pass
            else:
                raise AssertionError("Stop Redis before outage mode")
        else:
            assert support.client.ping()
        with Session(engine) as db, db.begin():
            now = database_time(db)
            hashed = hash_password(secrets.token_urlsafe(32))
            owner, attendee = [
                User(
                    id=uuid4(),
                    normalized_email=f"phase6-{run_id.hex}-{i}@example.com",
                    password_hash=hashed,
                    role="ORGANIZER" if i == 0 else "ATTENDEE",
                )
                for i in range(2)
            ]
            db.add_all([owner, attendee])
            db.flush()
            user_ids = [owner.id, attendee.id]
            event = Event(
                id=run_id,
                organizer_id=owner.id,
                title="Temporary Phase 6 smoke",
                description="Public metadata only",
                location="Local verification",
                starts_at=now + timedelta(days=2),
                ends_at=now + timedelta(days=2, hours=1),
                booking_closes_at=now + timedelta(days=1),
                status="PUBLISHED",
                capacity=2,
            )
            db.add(event)
            owner_session, attendee_session = (
                issue_session(db, settings, owner),
                issue_session(db, settings, attendee),
            )

        def credentials(session, key="smoke"):
            return {
                "Origin": settings.public_origin,
                "Cookie": f"{settings.session_cookie_name}={session.cookie}",
                "X-CSRF-Token": session.csrf_token,
                "Idempotency-Key": key,
            }

        check("ready", "GET", "/api/v1/health/ready", 200)
        bootstrap = check(
            "new-bootstrap-policy", "GET", "/api/v1/auth/csrf", 503 if mode == "outage" else 200
        )
        token = client.cookies.get(settings.session_cookie_name)
        if token:
            digests.add(token_digest(token))
        if mode == "outage":
            assert bootstrap.headers["retry-after"] == "1"
        existing = check(
            "existing-token", "GET", "/api/v1/auth/csrf", 200, headers=credentials(attendee_session)
        )
        assert existing.json()["csrf_token"] == attendee_session.csrf_token
        public = f"/api/v1/events/{run_id}"
        first = check("metadata-first", "GET", public, 200).json()
        assert "allocated_seats" not in first
        assert check("metadata-second", "GET", public, 200).json() == first
        if mode != "outage":
            assert support.client.exists(support.event_key(run_id))
            assert (
                0
                < support.client.pttl(support.event_key(run_id))
                <= settings.metadata_cache_ttl_seconds * 1000
            )
        changed = check(
            "metadata-edit",
            "PATCH",
            f"/api/v1/organizer/events/{run_id}",
            200,
            headers=credentials(owner_session),
            json={"title": "Changed Phase 6 smoke"},
        )
        assert changed.json()["title"] == "Changed Phase 6 smoke"
        if mode != "outage":
            assert not support.client.exists(support.event_key(run_id))
        assert (
            check("metadata-after-edit", "GET", public, 200).json()["title"]
            == "Changed Phase 6 smoke"
        )
        held = check(
            "hold", "POST", public + "/holds", 201, json={}, headers=credentials(attendee_session)
        )
        replay = check(
            "idempotent-retry",
            "POST",
            public + "/holds",
            201,
            json={},
            headers=credentials(attendee_session),
        )
        assert replay.json() == held.json() and replay.headers["idempotency-replayed"] == "true"
        reservation = f"/api/v1/reservations/{held.json()['id']}"
        for action, status in (("confirm", "CONFIRMED"), ("cancel", "CANCELLED")):
            response = check(
                action,
                "POST",
                reservation + "/" + action,
                200,
                json={},
                headers=credentials(attendee_session, action),
            )
            assert response.json()["status"] == status
        assert (
            check(
                "capacity",
                "PATCH",
                f"/api/v1/organizer/events/{run_id}/capacity",
                200,
                json={"capacity": 3},
                headers=credentials(owner_session),
            ).json()["capacity"]
            == 3
        )
        # Generate overdue work only under its event lock, then observe the independent worker.
        with Session(engine) as db, db.begin():
            event = db.scalar(select(Event).where(Event.id == run_id).with_for_update())
            now = database_time(db)
            overdue = Reservation(
                id=uuid4(),
                event_id=run_id,
                user_id=user_ids[1],
                status="HELD",
                created_at=now - timedelta(minutes=10),
                hold_expires_at=now - timedelta(minutes=1),
            )
            overdue_id = overdue.id
            db.add(overdue)
            event.allocated_seats += 1
        deadline = monotonic() + 60
        while True:
            with Session(engine) as db:
                if db.get(Reservation, overdue_id).status == "EXPIRED":
                    assert db.get(Event, run_id).allocated_seats == 0
                    break
            assert monotonic() < deadline, "Independent worker did not expire generated hold"
            sleep(0.1)
        assert (
            check("availability", "GET", public + "/availability", 200).json()["available_seats"]
            == 3
        )
        reconcile(engine)
        print(
            json.dumps(
                {
                    "event": "redis_smoke_passed",
                    "mode": mode,
                    "http_checks": len(results),
                    "worker_expired": 1,
                    "invariant_mismatches": 0,
                }
            )
        )
    finally:
        client.close()
        try:
            if user_ids:
                with Session(engine) as db, db.begin():
                    db.scalar(select(Event).where(Event.id == run_id).with_for_update())
                    db.execute(
                        delete(IdempotencyRecord).where(IdempotencyRecord.user_id.in_(user_ids))
                    )
                    db.execute(delete(Reservation).where(Reservation.event_id == run_id))
                    db.execute(delete(Event).where(Event.id == run_id))
                    db.execute(
                        delete(SessionRecord).where(
                            SessionRecord.user_id.in_(user_ids)
                            | SessionRecord.token_hash.in_(digests)
                        )
                    )
                    db.execute(delete(User).where(User.id.in_(user_ids)))
                support.invalidate(run_id)
            assert counts() == before, "Smoke must restore the original table counts"
            reconcile(engine)
        finally:
            support.close()
            engine.dispose()


if __name__ == "__main__":
    main()
