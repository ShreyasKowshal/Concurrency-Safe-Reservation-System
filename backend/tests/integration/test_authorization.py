import secrets
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from argon2 import PasswordHasher, Type
from fastapi import Depends
from psycopg import sql
from sqlalchemy import select, update
from sqlalchemy.engine import make_url

from csrs.auth.admin import promote_organizer, purge_sessions
from csrs.auth.crypto import PASSWORD_HASHER, token_digest
from csrs.auth.dependencies import CurrentUser, require_attendee, require_organizer, require_owner
from csrs.auth.service import database_time
from csrs.models import Role, SessionRecord, User

pytestmark = pytest.mark.integration
PASSWORD = "Correct horse battery staple 2026!"
ORIGIN = "http://localhost:5173"


def install_probes(app):
    # Test-only routes exercise guards without adding any Phase 3 production endpoints.
    @app.get("/test/organizer")
    def organizer(user: Annotated[User, Depends(require_organizer)]) -> dict:
        return {"id": str(user.id)}

    @app.get("/test/attendee")
    def attendee(user: Annotated[User, Depends(require_attendee)]) -> dict:
        return {"id": str(user.id)}

    @app.get("/test/owner/{owner_id}")
    def owner(owner_id: UUID, user: CurrentUser) -> dict:
        require_owner(owner_id, user)
        return {"id": str(user.id)}


def authenticate(client, email):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    result = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": ORIGIN, "X-CSRF-Token": token},
    )
    assert result.status_code == 200
    return result.json()["csrf_token"]


@pytest.mark.parametrize("role,status", [(Role.ATTENDEE, 403), (Role.ORGANIZER, 200)])
def test_role_and_owner_guards(client_factory, user_factory, role, status):
    user = user_factory(role=role)
    other = user_factory("other@example.com")
    with client_factory(configure=install_probes) as client:
        assert client.get("/test/organizer").status_code == 401
        authenticate(client, user.normalized_email)
        assert client.get("/test/organizer").status_code == status
        assert client.get("/test/attendee").status_code == 200
        assert client.get(f"/test/owner/{user.id}").status_code == 200
        assert client.get(f"/test/owner/{other.id}").status_code == 404


def test_local_promotion_revokes_existing_sessions(client, db, user_factory):
    user = user_factory()
    authenticate(client, user.normalized_email)
    promoted = promote_organizer(db, user.normalized_email)
    assert promoted.role == Role.ORGANIZER
    assert client.get("/api/v1/auth/me").status_code == 401
    authenticate(client, user.normalized_email)
    assert client.get("/api/v1/auth/me").json()["role"] == "ORGANIZER"


def test_local_promotion_requires_existing_active_user(db, user_factory):
    user_factory(active=False)
    with pytest.raises(ValueError):
        promote_organizer(db, "missing@example.com")
    with pytest.raises(ValueError):
        promote_organizer(db, "attendee@example.com")


def test_cookie_security_in_https_environment(
    client_factory, postgres_settings, user_factory, clean_engine
):
    user_factory()
    # Production settings now reject public example passwords. Use a generated,
    # least-privilege role in this disposable test DB, preserving real auth/SQL tests.
    role, password = "csrs_cookie_" + uuid4().hex, secrets.token_hex(32)
    identifier = sql.Identifier(role)
    with clean_engine.begin() as connection:
        driver = connection.connection.driver_connection
        driver.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(identifier, sql.Literal(password))
        )
        driver.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(identifier))
        driver.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(identifier)
        )
    try:
        url = make_url(postgres_settings.database_url.get_secret_value()).set(
            username=role, password=password
        )
        secure_settings = type(postgres_settings)(
            **{
                **postgres_settings.model_dump(),
                "environment": "production",
                "public_origin": "https://testserver",
                "database_url": url.render_as_string(hide_password=False),
            }
        )
        with client_factory(settings=secure_settings) as client:
            bootstrap = client.get("/api/v1/auth/csrf")
            header = bootstrap.headers["set-cookie"]
            assert header.startswith("__Host-csrs_session=")
            for required in ["Secure", "HttpOnly", "SameSite=lax", "Path=/", "Max-Age=900"]:
                assert required in header
            assert "Domain=" not in header
            result = client.post(
                "/api/v1/auth/login",
                json={"email": "attendee@example.com", "password": PASSWORD},
                headers={
                    "Origin": "https://testserver",
                    "X-CSRF-Token": bootstrap.json()["csrf_token"],
                },
            )
            assert result.status_code == 200 and "Max-Age=28800" in result.headers["set-cookie"]
            assert client.get("/api/v1/auth/me").status_code == 200
    finally:
        with clean_engine.begin() as connection:
            driver = connection.connection.driver_connection
            driver.execute(sql.SQL("DROP OWNED BY {}").format(identifier))
            driver.execute(sql.SQL("DROP ROLE {}").format(identifier))


def test_old_hash_is_upgraded_on_successful_login(client, db, user_factory):
    user_factory()
    old = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID)
    with db.begin():
        db.execute(update(User).values(password_hash=old.hash(PASSWORD)))
    authenticate(client, "attendee@example.com")
    with db.begin():
        assert not PASSWORD_HASHER.check_needs_rehash(db.scalar(select(User.password_hash)))


def test_session_cleanup_is_bounded_and_does_not_remove_active_sessions(client, db):
    client.get("/api/v1/auth/csrf")
    cookie = client.cookies["csrs_session"]
    with db.begin():
        from datetime import timedelta

        now = database_time(db)
        db.add_all(
            [
                SessionRecord(
                    kind="ANONYMOUS",
                    token_hash=str(i) * 64,
                    csrf_token="a" * 64,
                    created_at=now - timedelta(days=2),
                    expires_at=now - timedelta(days=1),
                )
                for i in range(3)
            ]
        )
    assert purge_sessions(db, batch_size=2) == 2
    assert purge_sessions(db, batch_size=2) == 1
    assert purge_sessions(db, batch_size=2) == 0
    with db.begin():
        assert (
            db.scalar(select(SessionRecord).where(SessionRecord.token_hash == token_digest(cookie)))
            is not None
        )


@pytest.mark.parametrize("batch_size", [0, -1, 10001])
def test_session_cleanup_rejects_invalid_batch_size(db, batch_size):
    with pytest.raises(ValueError):
        purge_sessions(db, batch_size)
