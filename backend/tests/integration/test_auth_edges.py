from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from csrs.auth import service
from csrs.auth.service import database_time
from csrs.models import SessionRecord, User

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:5173"
PASSWORD = "Correct horse battery staple 2026!"


def headers(client):
    result = client.get("/api/v1/auth/csrf")
    return {"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]}


@pytest.mark.parametrize("missing", ["cookie", "token", "mismatch", "origin", "null", "foreign"])
def test_authenticated_logout_rejects_csrf_bypasses(client, user_factory, missing):
    user_factory()
    result = client.post(
        "/api/v1/auth/login",
        json={"email": "attendee@example.com", "password": PASSWORD},
        headers=headers(client),
    )
    assert result.status_code == 200
    request_headers = {"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]}
    if missing == "cookie":
        client.cookies.clear()
    elif missing == "token":
        request_headers.pop("X-CSRF-Token")
    elif missing == "mismatch":
        request_headers["X-CSRF-Token"] = "0" * 64
    elif missing == "origin":
        request_headers.pop("Origin")
    elif missing == "null":
        request_headers["Origin"] = "null"
    else:
        request_headers["Origin"] = "http://evil.example"
    denied = client.post("/api/v1/auth/logout", json={}, headers=request_headers)
    assert denied.status_code == (401 if missing == "cookie" else 403)


def test_duplicate_origin_headers_are_rejected(client):
    csrf = headers(client)["X-CSRF-Token"]
    result = client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": PASSWORD},
        headers=[("Origin", ORIGIN), ("Origin", "http://evil.example"), ("X-CSRF-Token", csrf)],
    )
    assert result.status_code == 403


@pytest.mark.parametrize("password", ["too-short", "sensitive-" * 20])
def test_validation_errors_do_not_echo_password_values(client, password):
    result = client.post(
        "/api/v1/auth/register",
        headers=headers(client),
        json={"email": "new@example.com", "password": password},
    )
    assert result.status_code == 422
    assert password not in result.text
    assert all(set(item) == {"type", "loc", "msg"} for item in result.json()["detail"])


@pytest.mark.parametrize("endpoint", ["register", "login"])
def test_expiration_during_hashing_or_verification_is_rechecked(
    client,
    user_factory,
    clean_engine,
    monkeypatch,
    endpoint,
):
    user_factory()
    original_verify = service.verify_password
    original_hash = service.hash_password

    def expire():
        with Session(clean_engine) as db, db.begin():
            now = database_time(db)
            db.execute(
                update(SessionRecord).values(
                    created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1)
                )
            )

    def hash_then_expire(password):
        result = original_hash(password)
        expire()
        return result

    def verify_then_expire(encoded, password):
        result = original_verify(encoded, password)
        expire()
        return result

    monkeypatch.setattr(
        service,
        "hash_password" if endpoint == "register" else "verify_password",
        hash_then_expire if endpoint == "register" else verify_then_expire,
    )
    email = "new@example.com" if endpoint == "register" else "attendee@example.com"
    result = client.post(
        f"/api/v1/auth/{endpoint}",
        json={"email": email, "password": PASSWORD},
        headers=headers(client),
    )
    assert result.status_code == 403
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(SessionRecord)
                .where(SessionRecord.kind == "AUTHENTICATED")
            )
            == 0
        )


def test_registration_database_failure_rolls_back_user_and_session_rotation(
    client, db, monkeypatch
):
    csrf = headers(client)
    cookie = client.cookies["csrs_session"]
    original = service.issue_session

    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected test-only failure")

    monkeypatch.setattr(service, "issue_session", fail_after_insert)
    with pytest.raises(RuntimeError, match="injected test-only failure"):
        client.post(
            "/api/v1/auth/register",
            headers=csrf,
            json={"email": "new@example.com", "password": PASSWORD},
        )
    with db.begin():
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 1
    monkeypatch.setattr(service, "issue_session", original)
    assert client.cookies["csrs_session"] == cookie
    assert client.get("/api/v1/auth/csrf").json()["csrf_token"] == csrf["X-CSRF-Token"]


def test_competing_registration_consumes_one_pre_session(client, client_factory, db):
    csrf = headers(client)
    cookie = client.cookies["csrs_session"]
    barrier = Barrier(2)

    def attempt(contender):
        barrier.wait(timeout=10)
        return contender.post(
            "/api/v1/auth/register",
            headers=csrf,
            json={"email": "new@example.com", "password": PASSWORD},
        ).status_code

    with ExitStack() as clients:
        contenders = [clients.enter_context(client_factory()) for _ in range(2)]
        for contender in contenders:
            contender.cookies.set("csrs_session", cookie)
            # Materialize framework route/schema metadata before racing database commands.
            # Invalid input does not consume the shared pre-session or create a user.
            assert contender.post("/api/v1/auth/register", headers=csrf, json={}).status_code == 422
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(attempt, contenders))
    assert sorted(statuses) == [201, 403]
    with db.begin():
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 1


def test_local_cookie_flags_and_absolute_expiration_do_not_slide(client, db):
    first = client.get("/api/v1/auth/csrf")
    cookie = first.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Secure" not in cookie and "Domain=" not in cookie
    with db.begin():
        expiry = db.scalar(select(SessionRecord.expires_at))
    again = client.get("/api/v1/auth/csrf")
    assert again.json() == first.json() and "set-cookie" not in again.headers
    with db.begin():
        assert db.scalar(select(SessionRecord.expires_at)) == expiry
