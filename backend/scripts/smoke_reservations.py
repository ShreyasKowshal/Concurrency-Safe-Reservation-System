"""Live Compose smoke: temporary accounts/event, real proxy HTTP, scoped cleanup.

Run inside the development backend: python scripts/smoke_reservations.py
Requires the frontend proxy and migrated database. Prints labels/statuses, never tokens.
"""

import secrets
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx2
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from csrs.auth.admin import promote_organizer
from csrs.auth.crypto import token_digest
from csrs.auth.service import database_time
from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.models import Event, IdempotencyRecord, Reservation, SessionRecord, User


def main():
    settings = Settings()
    if settings.environment != "local":
        raise SystemExit("This smoke helper requires the local development environment.")
    engine = create_database_engine(settings)
    suffix = uuid4().hex
    emails = [f"phase4-{suffix}-{kind}@example.com" for kind in ("owner", "attendee")]
    password = secrets.token_urlsafe(32)
    digests, user_ids = set(), set()
    results = []
    tables = (User, SessionRecord, Event, Reservation, IdempotencyRecord)

    def counts():
        with Session(engine) as db:
            return {
                model.__tablename__: db.scalar(select(func.count()).select_from(model))
                for model in tables
            }

    before = counts()
    clients = [
        httpx2.Client(
            base_url="http://frontend:5173",
            timeout=10,
            trust_env=False,
            headers={"Host": urlsplit(settings.public_origin).netloc},
        )
        for _ in emails
    ]

    def check(client, label, method, path, expected, **kwargs):
        response = client.request(method, path, **kwargs)
        token = client.cookies.get(settings.session_cookie_name)
        if token:
            digests.add(token_digest(token))
        assert response.status_code == expected, (label, response.status_code)
        if path.startswith("/api/"):
            assert response.headers["cache-control"] == "no-store"
        results.append((label, response.status_code))
        return response

    try:
        owner, attendee = clients
        check(owner, "frontend", "GET", "/", 200)
        check(owner, "proxy-ready", "GET", "/api/v1/health/ready", 200)
        document = check(owner, "openapi", "GET", "http://backend:8000/openapi.json", 200).json()
        assert document["info"]["version"] == "0.4.0" and len(document["paths"]) == 20
        check(owner, "direct-ready", "GET", "http://backend:8000/api/v1/health/ready", 200)
        check(owner, "docs", "GET", "http://backend:8000/docs", 200)
        tokens = []
        for index, client in enumerate(clients):
            token = check(client, f"bootstrap-{index}", "GET", "/api/v1/auth/csrf", 200).json()[
                "csrf_token"
            ]
            header = {"Origin": settings.public_origin, "X-CSRF-Token": token}
            reply = check(
                client,
                f"register-{index}",
                "POST",
                "/api/v1/auth/register",
                201,
                headers=header,
                json={"email": emails[index], "password": password},
            )
            user_ids.add(UUID(reply.json()["user"]["id"]))
            header["X-CSRF-Token"] = reply.json()["csrf_token"]
            if index == 0:
                with Session(engine) as db:
                    promote_organizer(db, emails[index])
            reply = check(
                client,
                f"login-{index}",
                "POST",
                "/api/v1/auth/login",
                200,
                headers=header,
                json={"email": emails[index], "password": password},
            )
            tokens.append(
                {"Origin": settings.public_origin, "X-CSRF-Token": reply.json()["csrf_token"]}
            )
        owner_headers, attendee_headers = tokens
        with Session(engine) as db:
            now = database_time(db)
        body = {
            "title": "Temporary Phase 4 smoke",
            "location": "Smoke room",
            "capacity": 1,
            "starts_at": (now + timedelta(days=2)).isoformat(),
            "ends_at": (now + timedelta(days=2, hours=1)).isoformat(),
            "booking_closes_at": (now + timedelta(days=1)).isoformat(),
        }
        event_id = check(
            owner,
            "create-event",
            "POST",
            "/api/v1/organizer/events",
            201,
            headers=owner_headers,
            json=body,
        ).json()["id"]
        private, public = f"/api/v1/organizer/events/{event_id}", f"/api/v1/events/{event_id}"
        check(owner, "publish", "POST", private + "/publish", 200, headers=owner_headers, json={})
        assert (
            check(attendee, "availability-before", "GET", public + "/availability", 200).json()[
                "available_seats"
            ]
            == 1
        )
        key_headers = attendee_headers | {"Idempotency-Key": "hold"}
        held = check(attendee, "hold", "POST", public + "/holds", 201, headers=key_headers, json={})
        assert held.headers["idempotency-replayed"] == "false"
        reservation = f"/api/v1/reservations/{held.json()['id']}"
        replay = check(
            attendee,
            "response-loss-retry",
            "POST",
            public + "/holds",
            201,
            headers=key_headers,
            json={},
        )
        assert replay.json() == held.json() and replay.headers["idempotency-replayed"] == "true"
        check(
            attendee,
            "different-key-active",
            "POST",
            public + "/holds",
            409,
            headers=attendee_headers | {"Idempotency-Key": "active"},
            json={},
        )
        check(
            owner,
            "full",
            "POST",
            public + "/holds",
            409,
            headers=owner_headers | {"Idempotency-Key": "full"},
            json={},
        )
        check(owner, "foreign-detail", "GET", reservation, 404)
        check(
            owner,
            "foreign-cancel",
            "POST",
            reservation + "/cancel",
            404,
            headers=owner_headers | {"Idempotency-Key": "foreign"},
            json={},
        )
        check(
            attendee,
            "csrf-replay-denied",
            "POST",
            public + "/holds",
            403,
            headers=key_headers | {"X-CSRF-Token": "0" * 64},
            json={},
        )
        assert (
            check(attendee, "availability-held", "GET", public + "/availability", 200).json()[
                "available_seats"
            ]
            == 0
        )
        check(
            attendee,
            "confirm",
            "POST",
            reservation + "/confirm",
            200,
            headers=attendee_headers | {"Idempotency-Key": "confirm"},
            json={},
        )
        check(
            attendee,
            "repeat-confirm",
            "POST",
            reservation + "/confirm",
            200,
            headers=attendee_headers | {"Idempotency-Key": "confirm-again"},
            json={},
        )
        check(attendee, "history", "GET", "/api/v1/me/reservations?limit=1", 200)
        check(
            attendee,
            "cancel",
            "POST",
            reservation + "/cancel",
            200,
            headers=attendee_headers | {"Idempotency-Key": "cancel"},
            json={},
        )
        check(
            attendee,
            "repeat-cancel",
            "POST",
            reservation + "/cancel",
            200,
            headers=attendee_headers | {"Idempotency-Key": "cancel-again"},
            json={},
        )
        full_replay = check(
            owner,
            "stored-full-after-release",
            "POST",
            public + "/holds",
            409,
            headers=owner_headers | {"Idempotency-Key": "full"},
            json={},
        )
        assert full_replay.headers["idempotency-replayed"] == "true"
        held2 = check(
            attendee,
            "rebook",
            "POST",
            public + "/holds",
            201,
            headers=attendee_headers | {"Idempotency-Key": "rebook"},
            json={},
        ).json()
        # Make only this temporary hold overdue under the event lock to exercise live expiry.
        with Session(engine) as db, db.begin():
            db.scalar(select(Event).where(Event.id == UUID(event_id)).with_for_update())
            row = db.get(Reservation, UUID(held2["id"]))
            row.created_at = database_time(db) - timedelta(minutes=10)
            row.hold_expires_at = database_time(db) - timedelta(minutes=1)
        check(
            attendee,
            "expired-confirm",
            "POST",
            f"/api/v1/reservations/{held2['id']}/confirm",
            409,
            headers=attendee_headers | {"Idempotency-Key": "expired"},
            json={},
        )
        assert (
            check(attendee, "availability-reclaimed", "GET", public + "/availability", 200).json()[
                "available_seats"
            ]
            == 1
        )
        check(owner, "close", "POST", private + "/close", 200, headers=owner_headers, json={})
        check(
            attendee,
            "closed-hold",
            "POST",
            public + "/holds",
            409,
            headers=attendee_headers | {"Idempotency-Key": "closed"},
            json={},
        )
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT allocated_seats FROM events WHERE id=:id"), {"id": UUID(event_id)}
                )
                == 0
            )
    finally:
        for client in clients:
            client.close()
        with Session(engine) as db, db.begin():
            # Generated emails/IDs and collected digests only; never truncate development data.
            ids = list(db.scalars(select(User.id).where(User.normalized_email.in_(emails))))
            db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id.in_(ids)))
            db.execute(delete(Reservation).where(Reservation.user_id.in_(ids)))
            db.execute(delete(Event).where(Event.organizer_id.in_(ids)))
            db.execute(
                delete(SessionRecord).where(
                    or_(SessionRecord.user_id.in_(ids), SessionRecord.token_hash.in_(digests))
                )
            )
            db.execute(delete(User).where(User.id.in_(ids)))
        assert counts() == before, "Smoke cleanup did not restore table counts"
        engine.dispose()
    for label, status in results:
        print(f"{label}: {status}")
    print(f"{len(results)} live HTTP checks passed; original table counts restored.")


if __name__ == "__main__":
    main()
