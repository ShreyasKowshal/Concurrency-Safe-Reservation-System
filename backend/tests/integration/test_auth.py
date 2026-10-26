from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select, update

from csrs.auth.crypto import token_digest, verify_password
from csrs.auth.service import database_time
from csrs.models import SessionKind, SessionRecord, User

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:5173"
PASSWORD = "Correct horse battery staple 2026!"


def bootstrap(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def login(client, email="attendee@example.com", password=PASSWORD):
    headers = bootstrap(client)
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, headers=headers
    )


def test_registration_normalizes_email_hashes_password_and_rotates_pre_session(client, db):
    headers = bootstrap(client)
    previous_cookie = client.cookies["csrs_session"]
    result = client.post(
        "/api/v1/auth/register",
        json={
            "email": " Attendee@EXAMPLE.COM ",
            "password": PASSWORD,
        },
        headers=headers,
    )
    assert result.status_code == 201
    assert result.json()["user"]["email"] == "attendee@example.com"
    assert result.json()["user"]["role"] == "ATTENDEE"
    assert result.json()["csrf_token"] != headers["X-CSRF-Token"]
    assert client.cookies["csrs_session"] != previous_cookie
    assert client.get("/api/v1/auth/me").status_code == 401
    with db.begin():
        user = db.scalar(select(User))
        assert verify_password(user.password_hash, PASSWORD)
        records = db.scalars(select(SessionRecord)).all()
        assert len(records) == 1 and records[0].kind == SessionKind.ANONYMOUS
        assert records[0].token_hash == token_digest(client.cookies["csrs_session"])
        assert records[0].token_hash != client.cookies["csrs_session"]
    assert PASSWORD not in result.text and "password_hash" not in result.text


def test_login_me_bootstrap_logout_and_cookie_replay(client, db, user_factory):
    user = user_factory()
    old_headers = bootstrap(client)
    old_cookie = client.cookies["csrs_session"]
    result = client.post(
        "/api/v1/auth/login",
        json={"email": user.normalized_email, "password": PASSWORD},
        headers=old_headers,
    )
    assert result.status_code == 200
    cookie = client.cookies["csrs_session"]
    token = result.json()["csrf_token"]
    assert cookie != old_cookie and token != old_headers["X-CSRF-Token"]
    assert client.get("/api/v1/auth/me").json() == result.json()["user"]
    same = client.get("/api/v1/auth/csrf")
    assert same.json()["csrf_token"] == token and "set-cookie" not in same.headers
    rejected = client.post("/api/v1/auth/logout", json={}, headers=old_headers)
    assert rejected.status_code == 403
    result = client.post(
        "/api/v1/auth/logout", json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": token}
    )
    assert result.status_code == 204 and result.content == b""
    assert "Max-Age=0" in result.headers["set-cookie"]
    client.cookies.set("csrs_session", cookie)
    assert client.get("/api/v1/auth/me").status_code == 401
    with db.begin():
        assert (
            db.scalar(
                select(SessionRecord).where(SessionRecord.token_hash == token_digest(cookie))
            ).revoked_at
            is not None
        )
        assert (
            db.scalar(
                select(SessionRecord).where(SessionRecord.token_hash == token_digest(old_cookie))
            )
            is None
        )


@pytest.mark.parametrize(
    "email,password,active",
    [
        ("missing@example.com", PASSWORD, True),
        ("attendee@example.com", "incorrect password", True),
        ("attendee@example.com", PASSWORD, False),
    ],
)
def test_invalid_credentials_are_generic(client, user_factory, email, password, active):
    user_factory(active=active)
    result = login(client, email, password)
    assert result.status_code == 401
    assert result.json() == {
        "error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."}
    }
    assert result.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_duplicate_registration_does_not_consume_pre_session_or_create_account(
    client, db, user_factory
):
    user_factory()
    headers = bootstrap(client)
    result = client.post(
        "/api/v1/auth/register",
        json={"email": "ATTENDEE@example.com", "password": PASSWORD},
        headers=headers,
    )
    assert (
        result.status_code == 409 and result.json()["error"]["code"] == "REGISTRATION_UNAVAILABLE"
    )
    assert client.get("/api/v1/auth/csrf").json()["csrf_token"] == headers["X-CSRF-Token"]
    with db.begin():
        assert db.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize("role_field", ["role", "is_active", "user_id", "organizer_id"])
def test_registration_rejects_privilege_fields_without_echoing_password(client, db, role_field):
    result = client.post(
        "/api/v1/auth/register",
        headers=bootstrap(client),
        json={
            "email": "attendee@example.com",
            "password": PASSWORD,
            role_field: "ORGANIZER",
        },
    )
    assert result.status_code == 422 and PASSWORD not in result.text
    with db.begin():
        assert db.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize("endpoint", ["register", "login"])
@pytest.mark.parametrize(
    "missing",
    [
        "cookie",
        "token",
        "mismatch",
        "origin",
        "null",
        "hostile",
        "port",
        "scheme",
        "suffix",
        "referer",
    ],
)
def test_anonymous_csrf_and_origin_rejections(client, endpoint, missing):
    headers = bootstrap(client)
    if missing == "cookie":
        client.cookies.clear()
    elif missing == "token":
        headers.pop("X-CSRF-Token")
    elif missing == "mismatch":
        headers["X-CSRF-Token"] = "a" * 64
    elif missing == "origin":
        headers.pop("Origin")
    elif missing == "referer":
        headers.pop("Origin")
        headers["Referer"] = "http://evil.example/login"
    else:
        headers["Origin"] = {
            "null": "null",
            "hostile": "http://evil.example",
            "port": "http://localhost:5174",
            "scheme": "https://localhost:5173",
            "suffix": "http://localhost.evil.example:5173",
        }[missing]
    result = client.post(
        f"/api/v1/auth/{endpoint}",
        headers=headers,
        json={"email": "user@example.com", "password": PASSWORD},
    )
    assert result.status_code == 403 and result.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.parametrize("endpoint", ["register", "login", "logout"])
def test_json_media_type_is_required(client, endpoint):
    result = client.post(
        f"/api/v1/auth/{endpoint}", headers=bootstrap(client), data={"email": "user@example.com"}
    )
    assert result.status_code == 415


def test_trusted_referer_fallback_and_untrusted_origin_precedence(client, user_factory):
    user_factory()
    headers = bootstrap(client)
    headers.pop("Origin")
    headers["Referer"] = ORIGIN + "/login?from=home"
    result = client.post(
        "/api/v1/auth/login",
        json={"email": "attendee@example.com", "password": PASSWORD},
        headers=headers,
    )
    assert result.status_code == 200
    headers["Origin"] = "null"
    headers["X-CSRF-Token"] = result.json()["csrf_token"]
    assert client.post("/api/v1/auth/logout", json={}, headers=headers).status_code == 403


@pytest.mark.parametrize("kind", ["anonymous", "expired", "revoked", "inactive", "malformed"])
def test_invalid_sessions_cannot_authenticate(client, db, user_factory, kind):
    user = user_factory()
    headers = bootstrap(client)
    if kind != "anonymous":
        result = client.post(
            "/api/v1/auth/login",
            json={"email": user.normalized_email, "password": PASSWORD},
            headers=headers,
        )
        assert result.status_code == 200
    cookie = client.cookies["csrs_session"]
    if kind in {"expired", "revoked", "inactive"}:
        with db.begin():
            if kind == "expired":
                db.execute(
                    update(SessionRecord).values(
                        created_at=database_time(db) - timedelta(days=2),
                        expires_at=database_time(db) - timedelta(days=1),
                    )
                )
            elif kind == "revoked":
                db.execute(update(SessionRecord).values(revoked_at=database_time(db)))
            else:
                db.execute(update(User).values(is_active=False))
    if kind == "malformed":
        client.cookies.clear()
        client.cookies.set("csrs_session", "not-a-valid-token")
    assert client.get("/api/v1/auth/me").status_code == 401
    assert cookie not in client.get("/api/v1/auth/me").text


@pytest.mark.parametrize("endpoint", ["register", "login"])
def test_expired_pre_session_cannot_mutate(client, db, endpoint):
    headers = bootstrap(client)
    with db.begin():
        now = database_time(db)
        db.execute(
            update(SessionRecord).values(
                created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1)
            )
        )
    assert (
        client.post(
            f"/api/v1/auth/{endpoint}",
            headers=headers,
            json={"email": "user@example.com", "password": PASSWORD},
        ).status_code
        == 403
    )


def test_csrf_token_from_another_session_is_rejected(client, client_factory, user_factory):
    user_factory()
    with client_factory() as other:
        foreign = bootstrap(other)
    bootstrap(client)
    result = client.post(
        "/api/v1/auth/login",
        json={"email": "attendee@example.com", "password": PASSWORD},
        headers=foreign,
    )
    assert result.status_code == 403


def test_bootstrap_rejects_cross_site_requests(client):
    assert (
        client.get("/api/v1/auth/csrf", headers={"Origin": "http://evil.example"}).status_code
        == 403
    )
    assert (
        client.get("/api/v1/auth/csrf", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    )


def test_concurrent_login_consumes_pre_session_once(client, client_factory, user_factory, db):
    user_factory()
    headers = bootstrap(client)
    cookie = client.cookies["csrs_session"]
    barrier = Barrier(2)

    def attempt(contender):
        barrier.wait(timeout=10)
        return contender.post(
            "/api/v1/auth/login",
            json={"email": "attendee@example.com", "password": PASSWORD},
            headers=headers,
        ).status_code

    with ExitStack() as clients:
        contenders = [clients.enter_context(client_factory()) for _ in range(2)]
        for contender in contenders:
            contender.cookies.set("csrs_session", cookie)
            # Build lazy route metadata before the database concurrency barrier.
            # Invalid input leaves the shared pre-session available to both contenders.
            assert contender.post("/api/v1/auth/login", headers=headers, json={}).status_code == 422
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(attempt, contenders))
    assert sorted(statuses) == [200, 403]
    with db.begin():
        assert (
            db.scalar(
                select(func.count())
                .select_from(SessionRecord)
                .where(SessionRecord.kind == SessionKind.AUTHENTICATED)
            )
            == 1
        )
