"""Actual Redis operations plus PostgreSQL/API invariants; no fake server proves integration."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from threading import Event as Signal
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from sqlalchemy import event as sql_event
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_reservation_transactions import api_processes, http_post
from test_reservations import assert_consistent, headers, seed_reservation

from csrs.auth.service import database_time
from csrs.events import service as event_service
from csrs.models import Event, IdempotencyRecord, Reservation, SessionRecord, User
from csrs.redis_support import MAX_CACHE_BYTES, RedisSupport, SupportError
from csrs.worker import expire_event

pytestmark = [pytest.mark.integration, pytest.mark.redis]


@pytest.fixture
def redis_settings(postgres_settings):
    url = os.environ.get("CSRS_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set CSRS_TEST_REDIS_URL to a dedicated Redis test instance, database 15")
    from urllib.parse import urlsplit

    assert urlsplit(url).path == "/15", "Redis integration requires disposable test database 15"
    settings = postgres_settings.model_copy(
        update={
            "redis_url": url,
            "redis_namespace": "csrs_test_" + uuid4().hex,
            "rate_limits_enabled": True,
            "metadata_cache_enabled": True,
            "redis_max_connections": 40,
        }
    )
    # Validate copied URL and types, including SecretStr conversion.
    settings = type(settings)(**settings.model_dump())
    support = RedisSupport(settings)
    assert support.client.ping()
    try:
        yield settings
    finally:
        keys = list(support.client.scan_iter(match=f"{support.prefix}:*"))
        if keys:
            support.client.delete(*keys)
        support.close()


@pytest.fixture
def support(redis_settings):
    value = RedisSupport(redis_settings)
    try:
        yield value
    finally:
        value.close()


def unavailable(settings):
    return type(settings)(**(settings.model_dump() | {"redis_url": "redis://127.0.0.1:1/15"}))


def redis_now(client):
    seconds, microseconds = client.time()
    return seconds * 1000 + microseconds // 1000


def test_connection_reuse_and_bounded_pool(support):
    ids = [support.client.client_id() for _ in range(5)]
    assert len(set(ids)) == 1
    assert support.client.connection_pool.max_connections == 40
    assert support.client.connection_pool.connection_kwargs["socket_timeout"] == 0.2


def test_public_metadata_hit_avoids_description_load(
    booking, client_factory, redis_settings, support
):
    statements = []

    def record(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    with client_factory(redis_settings) as client:
        engine = client.app.state.database_engine
        sql_event.listen(engine, "before_cursor_execute", record)
        try:
            first = client.get(f"/api/v1/events/{booking['event'].id}")
            assert first.status_code == 200
            assert len(statements) == 2
            assert any("events.description" in statement for statement in statements)
            statements.clear()
            second = client.get(f"/api/v1/events/{booking['event'].id}")
            assert len(statements) == 1
            assert any("events.id" in statement for statement in statements)
            assert not any("events.description" in statement for statement in statements)
            assert second.json() == first.json()
            assert second.headers["cache-control"] == "no-store"
            assert "allocated_seats" not in second.json()
            assert client.get("/api/v1/events").status_code == 200
        finally:
            sql_event.remove(engine, "before_cursor_execute", record)
    key = support.event_key(booking["event"].id)
    assert 0 < support.client.pttl(key) <= 15000
    assert support.client.strlen(key) < MAX_CACHE_BYTES
    assert len(list(support.client.scan_iter(match=f"{support.prefix}:event:*"))) == 1


@pytest.mark.parametrize("action", ["edit", "capacity", "close"])
def test_metadata_invalidation_follows_committed_event_change(
    booking, client_factory, redis_settings, support, clean_engine, action
):
    event = booking["event"]
    with client_factory(redis_settings) as client:
        assert client.get(f"/api/v1/events/{event.id}").status_code == 200
        key = support.event_key(event.id)
        assert support.client.exists(key)
        path = f"/api/v1/organizer/events/{event.id}"
        body = {"title": "Changed title"}
        if action == "capacity":
            path += "/capacity"
            body = {"capacity": 12}
        elif action == "close":
            path += "/close"
            body = {}
        response = getattr(client, "post" if action == "close" else "patch")(
            path, json=body, headers=headers(booking, actor=booking["owner_session"])
        )
        assert response.status_code == 200
        assert support.client.exists(key) == 0
        latest = client.get(f"/api/v1/events/{event.id}")
        if action == "close":
            assert latest.status_code == 404
        else:
            assert latest.json()["title" if action == "edit" else "capacity"] == (
                "Changed title" if action == "edit" else 12
            )
    assert_consistent(clean_engine)


def test_publish_and_private_visibility_are_never_authorized_by_cache(
    booking, event_factory, client_factory, redis_settings, support
):
    draft = event_factory(booking["owner"])
    body = event_service.EventDetail.model_validate(draft).model_dump(mode="json") | {
        "status": "PUBLISHED"
    }
    support.client.set(
        support.event_key(draft.id), json.dumps({"version": 1, "event": body}), ex=15
    )
    with client_factory(redis_settings) as client:
        assert client.get(f"/api/v1/events/{draft.id}").status_code == 404
        reply = client.post(
            f"/api/v1/organizer/events/{draft.id}/publish",
            json={},
            headers=headers(booking, actor=booking["owner_session"]),
        )
        assert reply.status_code == 200
        assert not support.client.exists(support.event_key(draft.id))
        assert client.get(f"/api/v1/events/{draft.id}").status_code == 200


@pytest.mark.parametrize(
    "corruption",
    [
        "json",
        "version",
        "missing-version",
        "wrong-event",
        "private",
        "state",
        "no-ttl",
        "oversize",
        "wrong-type",
    ],
)
def test_invalid_cache_data_falls_back_to_postgresql(
    booking, client_factory, redis_settings, support, corruption
):
    event_id = booking["event"].id
    key = support.event_key(event_id)
    with client_factory(redis_settings) as client:
        original = client.get(f"/api/v1/events/{event_id}").json()
        value = {"version": 1, "event": original.copy()}
        value["event"]["title"] = "Invalid cache entry must not be returned"
        if corruption == "version":
            value["version"] = 2
        elif corruption == "missing-version":
            del value["version"]
        elif corruption == "wrong-event":
            value["event"]["id"] = str(uuid4())
        elif corruption == "private":
            value["event"]["allocated_seats"] = 10
        elif corruption == "state":
            value["event"]["status"] = "DRAFT"
        payload = json.dumps(value)
        if corruption == "json":
            payload = "not-json"
        elif corruption == "oversize":
            payload = "x" * (MAX_CACHE_BYTES + 1)
        support.client.set(key, payload, ex=None if corruption == "no-ttl" else 15)
        if corruption == "wrong-type":
            support.client.delete(key)
            support.client.lpush(key, "bad")
            support.client.expire(key, 15)
        statements = []

        def observed(conn, cursor, statement, parameters, context, many):
            statements.append(statement)

        engine = client.app.state.database_engine
        sql_event.listen(engine, "before_cursor_execute", observed)
        try:
            response = client.get(f"/api/v1/events/{event_id}")
        finally:
            sql_event.remove(engine, "before_cursor_execute", observed)
        assert response.status_code == 200 and response.json() == original
        assert any("events.description" in statement for statement in statements)


def test_cache_ttl_expiration_and_event_isolation(
    booking, event_factory, client_factory, redis_settings, support
):
    another = event_factory(booking["owner"], title="Other", status="PUBLISHED")
    with client_factory(redis_settings) as client:
        for event_id in (booking["event"].id, another.id):
            assert client.get(f"/api/v1/events/{event_id}").status_code == 200
        key = support.event_key(booking["event"].id)
        support.client.pexpireat(key, redis_now(support.client) - 1)
        assert support.lookup(booking["event"].id)[0] is None
        assert support.lookup(another.id)[0].title == "Other"
        assert client.get(f"/api/v1/events/{booking['event'].id}").status_code == 200
        assert support.lookup(booking["event"].id)[0] is not None


def test_older_read_after_invalidation_has_original_absolute_deadline(
    booking, client_factory, redis_settings, support, monkeypatch
):
    read_done, release = Signal(), Signal()
    original = event_service.get_public_event
    tickets = []
    lookup = RedisSupport.lookup

    def track(self, event_id):
        result = lookup(self, event_id)
        if result[1]:
            tickets.append(result[1])
        return result

    def gated(db, event_id):
        result = original(db, event_id)
        read_done.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(RedisSupport, "lookup", track)
    with client_factory(redis_settings) as reader, client_factory(redis_settings) as writer:
        # Materialize lazy endpoint metadata before the actual coordinated race.
        assert reader.get("/api/v1/events/not-a-uuid").status_code == 422
        assert writer.patch("/api/v1/organizer/events/not-a-uuid", json={}).status_code in {
            403,
            422,
        }
        monkeypatch.setattr(event_service, "get_public_event", gated)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reader.get, f"/api/v1/events/{booking['event'].id}")
            try:
                assert read_done.wait(10)
                updated = writer.patch(
                    f"/api/v1/organizer/events/{booking['event'].id}",
                    json={"title": "New"},
                    headers=headers(booking, actor=booking["owner_session"]),
                )
                assert updated.status_code == 200
                assert not support.client.exists(support.event_key(booking["event"].id))
                # Explicit clock ordering makes a fresh-TTL stale fill distinguishable.
                start_ms = tickets[0].deadline_ms - redis_settings.metadata_cache_ttl_seconds * 1000
                clock_deadline = time.monotonic() + 2
                while redis_now(support.client) <= start_ms:
                    assert time.monotonic() < clock_deadline
            finally:
                release.set()
            assert future.result(timeout=10).json()["title"] != "New"
        assert support.client.pexpiretime(tickets[0].key) == tickets[0].deadline_ms
        # An arbitrarily delayed old read cannot repopulate after its original bound.
        support.invalidate(booking["event"].id)
        expired_ticket = replace(tickets[0], deadline_ms=redis_now(support.client) - 1)
        with Session(reader.app.state.database_engine) as db:
            latest = original(db, booking["event"].id)
        support.fill(expired_ticket, latest)
        assert not support.client.exists(expired_ticket.key)


def test_failed_postcommit_invalidation_cannot_expose_closed_event(
    booking, client_factory, redis_settings, support, clean_engine
):
    event_id = booking["event"].id
    with client_factory(redis_settings) as healthy:
        assert healthy.get(f"/api/v1/events/{event_id}").status_code == 200
        with client_factory(unavailable(redis_settings)) as degraded:
            reply = degraded.post(
                f"/api/v1/organizer/events/{event_id}/close",
                json={},
                headers=headers(booking, actor=booking["owner_session"]),
            )
            assert reply.status_code == 200
        assert support.client.exists(support.event_key(event_id))
        assert healthy.get(f"/api/v1/events/{event_id}").status_code == 404
    assert_consistent(clean_engine)


def test_atomic_quota_under_concurrent_connections(support):
    start = Barrier(16)

    def attempt(_):
        start.wait(10)
        try:
            support.quota("bootstrap", "one-peer", 5, required=True)
            return 200
        except SupportError as error:
            assert error.retry_after >= 1
            return error.status

    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(attempt, range(16)))
    assert outcomes.count(200) == 5 and outcomes.count(429) == 11
    keys = list(support.client.scan_iter(match=f"{support.prefix}:quota:*"))
    assert len(keys) == 1 and support.client.get(keys[0]) == b"5"
    assert 0 < support.client.pttl(keys[0]) <= 60000


def test_quota_shared_across_two_independent_api_processes(redis_settings, clean_engine):
    settings = redis_settings.model_copy(update={"rate_limit_bootstrap": 3})
    start = Barrier(10)
    with api_processes(settings) as addresses:

        def attempt(index):
            start.wait(10)
            request = Request(
                addresses[index % 2] + "/api/v1/auth/csrf",
                headers={"X-Forwarded-For": f"192.0.2.{index + 1}"},
            )
            try:
                response = urlopen(request, timeout=10)
            except HTTPError as error:
                response = error
            with response:
                return response.status

        with ThreadPoolExecutor(max_workers=10) as pool:
            outcomes = list(pool.map(attempt, range(10)))
    assert outcomes.count(200) == 3 and outcomes.count(429) == 7
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 3


def test_quota_identity_forwarded_headers_and_window_reset(client_factory, redis_settings, support):
    settings = redis_settings.model_copy(update={"rate_limit_bootstrap": 1})
    with client_factory(settings) as client:
        assert (
            client.get("/api/v1/auth/csrf", headers={"X-Forwarded-For": "192.0.2.1"}).status_code
            == 200
        )
        client.cookies.clear()
        denied = client.get("/api/v1/auth/csrf", headers={"X-Forwarded-For": "192.0.2.2"})
        assert denied.status_code == 429 and int(denied.headers["retry-after"]) >= 1
        key = list(support.client.scan_iter(match=f"{support.prefix}:quota:bootstrap:*"))[0]
        support.client.pexpireat(key, redis_now(support.client) - 1)
        assert client.get("/api/v1/auth/csrf").status_code == 200


def test_throttle_replay_csrf_and_no_partial_claims(
    booking, client_factory, redis_settings, support, clean_engine
):
    settings = redis_settings.model_copy(update={"rate_limit_mutation": 1})
    path = f"/api/v1/events/{booking['event'].id}/holds"
    with client_factory(settings) as client:
        first = client.post(path, json={}, headers=headers(booking))
        assert first.status_code == 201
        assert client.post(path, json={}, headers=headers(booking, "other-key")).status_code == 429
        assert client.post(path, json={}, headers=headers(booking)).status_code == 429
        assert (
            client.post(
                path, json={}, headers=headers(booking) | {"X-CSRF-Token": "0" * 64}
            ).status_code
            == 403
        )
        with Session(clean_engine) as db:
            assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
        key = list(support.client.scan_iter(match=f"{support.prefix}:quota:mutation:*"))[0]
        support.client.pexpireat(key, redis_now(support.client) - 1)
        replay = client.post(path, json={}, headers=headers(booking))
        assert replay.status_code == 201 and replay.json() == first.json()
        assert replay.headers["idempotency-replayed"] == "true"
    assert_consistent(clean_engine)


def test_auth_outage_fails_closed_without_creating_sessions_or_users(
    booking, client_factory, redis_settings, clean_engine
):
    with Session(clean_engine) as db:
        before = db.scalar(select(func.count()).select_from(SessionRecord))
        before_users = db.scalar(select(func.count()).select_from(User))
    with client_factory(unavailable(redis_settings)) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        assert client.get("/api/v1/health/ready").status_code == 200
        for path in ("csrf", "register", "login"):
            reply = (
                client.get("/api/v1/auth/csrf")
                if path == "csrf"
                else client.post(
                    f"/api/v1/auth/{path}",
                    json={"email": "new@example.com", "password": "long password for outage test"},
                    headers={"Origin": "http://localhost:5173"},
                )
            )
            assert reply.status_code == 503
            assert reply.json()["error"]["code"] == "TEMPORARILY_UNAVAILABLE"
            assert reply.headers["retry-after"] == "1"
        assert (
            client.post("/api/v1/auth/logout", json={}, headers=headers(booking)).status_code == 204
        )
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == before
        assert db.scalar(select(func.count()).select_from(User)) == before_users


def test_reservation_lifecycle_and_capacity_edit_survive_actual_redis_connection_failure(
    booking, client_factory, redis_settings, clean_engine
):
    with client_factory(unavailable(redis_settings)) as client:
        path = f"/api/v1/events/{booking['event'].id}/holds"
        hold = client.post(path, json={}, headers=headers(booking))
        assert hold.status_code == 201
        assert client.post(path, json={}, headers=headers(booking)).json() == hold.json()
        reservation_id = hold.json()["id"]
        for action in ("confirm", "cancel"):
            result = client.post(
                f"/api/v1/reservations/{reservation_id}/{action}",
                json={},
                headers=headers(booking, action),
            )
            assert result.status_code == 200
            assert (
                result.json()["status"] == {"confirm": "CONFIRMED", "cancel": "CANCELLED"}[action]
            )
        edited = client.patch(
            f"/api/v1/organizer/events/{booking['event'].id}/capacity",
            json={"capacity": 2},
            headers=headers(booking, actor=booking["owner_session"]),
        )
        assert edited.status_code == 200 and edited.json()["capacity"] == 2
        assert client.get(f"/api/v1/events/{booking['event'].id}").status_code == 200
    assert_consistent(clean_engine)


@pytest.mark.parametrize("actor", ["request", "worker"])
def test_request_and_worker_expiration_independent_of_redis(
    booking, client_factory, redis_settings, clean_engine, actor
):
    old = seed_reservation(clean_engine, booking, due=True)
    with client_factory(unavailable(redis_settings)) as client:
        if actor == "request":
            response = client.post(
                f"/api/v1/events/{booking['event'].id}/holds", json={}, headers=headers(booking)
            )
            assert response.status_code == 201
        else:
            assert expire_event(clean_engine, booking["event"].id, 10).expired == 1
            assert expire_event(clean_engine, booking["event"].id, 10).expired == 0
        with Session(clean_engine) as db:
            assert db.get(Reservation, old.id).status == "EXPIRED"
    assert_consistent(clean_engine)


@pytest.mark.parametrize("mode", ["different-users", "same-user", "same-key"])
def test_admission_two_api_processes_with_redis_unavailable(
    booking, clean_engine, redis_settings, user_factory, mode
):
    with Session(clean_engine) as db, db.begin():
        db.get(Event, booking["event"].id).capacity = 1
    identities = [booking["session"], booking["session"]]
    if mode == "different-users":
        identities[1] = booking["credentials"](user_factory("rival@example.com"))
    start = Barrier(2)
    with api_processes(unavailable(redis_settings)) as addresses:

        def attempt(index):
            start.wait(10)
            return http_post(
                f"{addresses[index]}/api/v1/events/{booking['event'].id}/holds",
                headers(
                    booking,
                    "shared" if mode == "same-key" else f"outage-{index}",
                    identities[index],
                ),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
    if mode == "same-key":
        assert all(status == 201 for status, _, _ in results)
        assert results[0][1] == results[1][1]
        assert sorted(replayed for _, _, replayed in results) == ["false", "true"]
    else:
        assert sorted(status for status, _, _ in results) == [201, 409]
        expected = "EVENT_FULL" if mode == "different-users" else "ACTIVE_RESERVATION_EXISTS"
        assert (
            next(body for status, body, _ in results if status == 409)["error"]["code"] == expected
        )
    assert_consistent(clean_engine)


def test_real_socket_timeout_fallback_and_same_client_recovery(support, redis_settings):
    impatient = RedisSupport(
        redis_settings.model_copy(update={"redis_socket_timeout_seconds": 0.05})
    )
    try:
        assert impatient.client.ping()
        # The command acknowledgement establishes that the dedicated test server is paused.
        support.client.client_pause(300, "ALL")
        started = time.monotonic()
        assert impatient.lookup(uuid4()) == (None, None)
        elapsed = time.monotonic() - started
        assert elapsed < 1, "Redis operation unexpectedly retried or hung"
        deadline = time.monotonic() + 3
        while True:
            try:
                if impatient.client.ping():
                    break
            except Exception:
                assert time.monotonic() < deadline
        assert impatient.lookup(uuid4())[1] is not None
    finally:
        impatient.close()


def test_existing_csrf_token_available_during_outage_without_new_session(
    booking, client_factory, redis_settings, clean_engine
):
    with Session(clean_engine) as db:
        before = db.scalar(select(func.count()).select_from(SessionRecord))
    with client_factory(unavailable(redis_settings)) as client:
        reply = client.get("/api/v1/auth/csrf", headers=headers(booking))
        assert reply.status_code == 200
        assert reply.json()["csrf_token"] == booking["session"].csrf_token
        assert "set-cookie" not in reply.headers
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == before


def test_public_and_auth_quota_scopes_are_independent(
    booking, client_factory, redis_settings, support
):
    settings = redis_settings.model_copy(update={"rate_limit_public": 1, "rate_limit_auth": 1})
    with client_factory(settings) as client:
        assert client.get(f"/api/v1/events/{booking['event'].id}").status_code == 200
        assert client.get(f"/api/v1/events/{booking['event'].id}/availability").status_code == 429
        csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        auth_headers = {"Origin": "http://localhost:5173", "X-CSRF-Token": csrf}
        body = {"email": "unknown@example.com", "password": "wrong password"}
        assert client.post("/api/v1/auth/login", json=body, headers=auth_headers).status_code == 401
        assert client.post("/api/v1/auth/login", json=body, headers=auth_headers).status_code == 429
        # Existing token retrieval remains safe even after the public/auth quotas are exhausted.
        assert client.get("/api/v1/auth/csrf").json()["csrf_token"] == csrf


def test_distinct_authenticated_users_have_distinct_mutation_quotas(
    booking, user_factory, client_factory, redis_settings, clean_engine
):
    second = booking["credentials"](user_factory("second-limiter@example.com"))
    settings = redis_settings.model_copy(update={"rate_limit_mutation": 1})
    path = f"/api/v1/events/{booking['event'].id}/holds"
    with client_factory(settings) as client:
        assert client.post(path, json={}, headers=headers(booking)).status_code == 201
        assert (
            client.post(path, json={}, headers=headers(booking, "second", second)).status_code
            == 201
        )
        assert client.post(path, json={}, headers=headers(booking, "third")).status_code == 429
    assert_consistent(clean_engine)


def test_postgresql_failure_is_not_hidden_by_a_metadata_hit(
    booking, client_factory, redis_settings, clean_engine
):
    settings = redis_settings.model_copy(update={"db_statement_timeout_ms": 100})
    with client_factory(settings) as client:
        assert client.get(f"/api/v1/events/{booking['event'].id}").status_code == 200
        with clean_engine.connect() as connection, connection.begin():
            connection.execute(text("LOCK TABLE events IN ACCESS EXCLUSIVE MODE"))
            reply = client.get(f"/api/v1/events/{booking['event'].id}")
            assert reply.status_code == 503
            assert reply.json()["error"]["message"] == "The database is temporarily unavailable."
        assert client.get(f"/api/v1/events/{booking['event'].id}").status_code == 200


def test_rollback_does_not_invalidate_or_publish_uncommitted_metadata(
    booking, client_factory, redis_settings, support
):
    with client_factory(redis_settings) as client:
        original = client.get(f"/api/v1/events/{booking['event'].id}").json()
        key = support.event_key(booking["event"].id)
        cached_before = support.client.get(key)
        rejected = client.patch(
            f"/api/v1/organizer/events/{booking['event'].id}",
            json={"starts_at": booking["event"].starts_at.isoformat()},
            headers=headers(booking, actor=booking["owner_session"]),
        )
        assert rejected.status_code == 409
        assert support.client.get(key) == cached_before
        assert client.get(f"/api/v1/events/{booking['event'].id}").json() == original


def test_exhausted_pool_obeys_required_and_optional_quota_policy(redis_settings):
    value = RedisSupport(redis_settings.model_copy(update={"redis_max_connections": 1}))
    connection = value.client.connection_pool.get_connection()
    try:
        with pytest.raises(SupportError) as error:
            value.quota("bootstrap", "peer", 1, required=True)
        assert error.value.status == 503
        value.quota("mutation", "user", 1)
        assert value.lookup(uuid4()) == (None, None)
    finally:
        value.client.connection_pool.release(connection)
        assert value.client.ping()
        value.close()


def test_stale_metadata_across_processes_cannot_authorize_final_seat(
    booking, user_factory, client_factory, redis_settings, support, clean_engine
):
    event_id = booking["event"].id
    with client_factory(redis_settings) as reader:
        assert reader.get(f"/api/v1/events/{event_id}").json()["capacity"] == 10
        # A real refused Redis connection makes post-commit invalidation fail.
        with client_factory(unavailable(redis_settings)) as writer:
            result = writer.patch(
                f"/api/v1/organizer/events/{event_id}/capacity",
                json={"capacity": 1},
                headers=headers(booking, actor=booking["owner_session"]),
            )
            assert result.status_code == 200
        assert reader.get(f"/api/v1/events/{event_id}").json()["capacity"] == 10
        assert reader.get(f"/api/v1/events/{event_id}/availability").json()["capacity"] == 1
    identities = [
        booking["session"],
        booking["credentials"](user_factory("cache-rival@example.com")),
    ]
    start = Barrier(2)
    with api_processes(redis_settings) as addresses:

        def attempt(index):
            # Both processes consume the same stale Redis metadata, then race actual admission.
            with urlopen(addresses[index] + f"/api/v1/events/{event_id}", timeout=10) as response:
                assert json.load(response)["capacity"] == 10
            start.wait(10)
            return http_post(
                addresses[index] + f"/api/v1/events/{event_id}/holds",
                headers(booking, f"cached-{index}", identities[index]),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))
    assert sorted(status for status, _, _ in outcomes) == [201, 409]
    assert_consistent(clean_engine)


def test_cache_updates_and_invalidation_across_independent_api_processes(
    booking, redis_settings, support, clean_engine
):
    event_id = booking["event"].id
    with api_processes(redis_settings) as addresses:
        with urlopen(addresses[0] + f"/api/v1/events/{event_id}", timeout=10) as response:
            assert json.load(response)["title"] == booking["event"].title
        assert support.client.exists(support.event_key(event_id))
        request = Request(
            addresses[1] + f"/api/v1/organizer/events/{event_id}",
            method="PATCH",
            data=json.dumps({"title": "Other process"}).encode(),
            headers=headers(booking, actor=booking["owner_session"])
            | {"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            assert response.status == 200
        assert not support.client.exists(support.event_key(event_id))
        with urlopen(addresses[0] + f"/api/v1/events/{event_id}", timeout=10) as response:
            assert json.load(response)["title"] == "Other process"
    assert_consistent(clean_engine)


def test_real_ttl_and_quota_window_expire_without_refreshing_hits(
    booking, client_factory, redis_settings
):
    settings = redis_settings.model_copy(
        update={
            "metadata_cache_ttl_seconds": 1,
            "rate_limit_window_seconds": 1,
        }
    )
    value = RedisSupport(settings)
    try:
        with client_factory(settings) as client:
            assert client.get(f"/api/v1/events/{booking['event'].id}").status_code == 200
        key = value.event_key(booking["event"].id)
        value.quota("test-window", "one", 1, required=True)
        deadline = value.client.pexpiretime(key)
        assert value.lookup(booking["event"].id)[0] is not None
        assert value.client.pexpiretime(key) == deadline
        with pytest.raises(SupportError) as rejected:
            value.quota("test-window", "one", 1, required=True)
        assert rejected.value.status == 429
        # Observe actual Redis expiration; no sleep establishes a concurrent operation order.
        until = time.monotonic() + 5
        keys = list(value.client.scan_iter(match=f"{value.prefix}:quota:test-window:*"))
        while value.client.exists(key, *keys):
            assert time.monotonic() < until
            time.sleep(0.01)
        assert value.lookup(booking["event"].id)[0] is None
        value.quota("test-window", "one", 1, required=True)
    finally:
        value.close()


def test_reservation_transitions_do_not_cache_live_occupancy(
    booking, client_factory, redis_settings, support, clean_engine
):
    event_id = booking["event"].id
    with client_factory(redis_settings) as client:
        metadata = client.get(f"/api/v1/events/{event_id}").json()
        key = support.event_key(event_id)
        payload = support.client.get(key)
        hold = client.post(f"/api/v1/events/{event_id}/holds", json={}, headers=headers(booking))
        assert hold.status_code == 201
        assert client.get(f"/api/v1/events/{event_id}/availability").json()["available_seats"] == 9
        for action in ("confirm", "cancel"):
            assert (
                client.post(
                    f"/api/v1/reservations/{hold.json()['id']}/{action}",
                    json={},
                    headers=headers(booking, action),
                ).status_code
                == 200
            )
        assert client.get(f"/api/v1/events/{event_id}/availability").json()["available_seats"] == 10
        seed_reservation(clean_engine, booking, due=True)
        assert expire_event(clean_engine, event_id, 10).expired == 1
        assert support.client.get(key) == payload
        assert client.get(f"/api/v1/events/{event_id}").json() == metadata
        assert len(list(support.client.scan_iter(match=f"{support.prefix}:event:*"))) == 1
    assert_consistent(clean_engine)


def test_invalidation_observes_committed_state_and_no_event_lock(
    booking, client_factory, redis_settings, clean_engine, monkeypatch
):
    original = RedisSupport.invalidate
    observed = []

    def verify(self, event_id):
        with Session(clean_engine) as db, db.begin():
            row = db.scalar(select(Event).where(Event.id == event_id).with_for_update(nowait=True))
            assert row.title == "Already committed"
            observed.append(event_id)
        original(self, event_id)

    monkeypatch.setattr(RedisSupport, "invalidate", verify)
    with client_factory(redis_settings) as client:
        response = client.patch(
            f"/api/v1/organizer/events/{booking['event'].id}",
            json={"title": "Already committed"},
            headers=headers(booking, actor=booking["owner_session"]),
        )
        assert response.status_code == 200
    assert observed == [booking["event"].id]


def test_revoked_session_during_redis_wait_cannot_mutate_or_claim_key(
    booking, client_factory, redis_settings, clean_engine, monkeypatch
):
    entered, release = Signal(), Signal()
    quota = RedisSupport.quota

    def gated(self, scope, *args, **kwargs):
        if scope == "mutation":
            entered.set()
            assert release.wait(10)
        return quota(self, scope, *args, **kwargs)

    monkeypatch.setattr(RedisSupport, "quota", gated)
    with client_factory(redis_settings) as client, ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.post,
            f"/api/v1/events/{booking['event'].id}/holds",
            json={},
            headers=headers(booking),
        )
        try:
            assert entered.wait(10)
            with Session(clean_engine) as db, db.begin():
                for record in db.scalars(
                    select(SessionRecord).where(SessionRecord.user_id == booking["user"].id)
                ):
                    record.revoked_at = database_time(db)
        finally:
            release.set()
        assert future.result(timeout=10).status_code == 401
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
        assert db.scalar(select(func.count()).select_from(Reservation)) == 0
    assert_consistent(clean_engine)


def test_valid_sql_detail_outside_cache_limits_remains_readable(
    booking, event_factory, client_factory, redis_settings, support
):
    # Valid SQL/output data, although the API intentionally caps NEW description input.
    existing = event_factory(booking["owner"], status="PUBLISHED", description="x" * 10001)
    with client_factory(redis_settings) as client:
        response = client.get(f"/api/v1/events/{existing.id}")
        assert response.status_code == 200
        assert response.json()["description"] == existing.description
        assert not support.client.exists(support.event_key(existing.id))
        cacheable = event_factory(
            booking["owner"],
            status="PUBLISHED",
            title="  Existing title  ",
            location="  Room 101  ",
        )
        for _ in range(2):
            result = client.get(f"/api/v1/events/{cacheable.id}")
            assert result.status_code == 200
            assert result.json()["title"] == cacheable.title
            assert result.json()["location"] == cacheable.location
        assert support.client.exists(support.event_key(cacheable.id))
