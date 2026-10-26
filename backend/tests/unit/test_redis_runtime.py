"""Deterministic failure-policy/configuration checks complement actual Redis integration."""

import logging
import socket
import ssl
from threading import Event as Signal
from time import monotonic
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from redis.exceptions import ConnectionError, TimeoutError

from csrs.config import Settings
from csrs.main import create_app
from csrs.redis_connection import BoundedResolver, BoundedSSLConnection
from csrs.redis_support import RedisSupport, SupportError


@pytest.mark.parametrize(
    "url",
    [
        "redis://host/0?socket_timeout=100",
        "redis://host/0?decode_responses=yes",
        "redis://host/0#fragment",
        "redis://host/not-a-database",
    ],
)
def test_url_cannot_override_bounded_client_configuration(settings, url):
    with pytest.raises(ValidationError):
        Settings(**(settings.model_dump() | {"redis_url": url}))


@pytest.mark.parametrize(
    "changes",
    [
        {"redis_connect_timeout_seconds": 0},
        {"redis_socket_timeout_seconds": 3},
        {"redis_max_connections": 0},
        {"metadata_cache_ttl_seconds": 61},
        {"rate_limit_window_seconds": 0},
        {"rate_limit_bootstrap": 0},
        {"rate_limit_auth": 10001},
        {"rate_limit_public": -1},
        {"rate_limit_mutation": 0},
        {"redis_namespace": "unsafe:namespace"},
    ],
)
def test_redis_settings_fail_early(settings, changes):
    with pytest.raises(ValidationError):
        Settings(**(settings.model_dump() | changes))


@pytest.mark.parametrize(
    "error", [ConnectionError("secret-redis-password"), TimeoutError("secret-redis-password")]
)
def test_required_quota_fails_closed_optional_operations_fall_back(settings, error, caplog):
    settings = settings.model_copy(
        update={"rate_limits_enabled": True, "metadata_cache_enabled": True}
    )
    support = RedisSupport(settings)
    support.client = MagicMock()
    support.client.eval.side_effect = error
    support.client.delete.side_effect = error
    with caplog.at_level(logging.INFO, logger="csrs.redis"):
        with pytest.raises(SupportError) as raised:
            support.quota("bootstrap", "private-user-identity", 1, required=True)
        assert raised.value.status == 503
        support.quota("mutation", "private-user-identity", 1)
        assert support.lookup(uuid4()) == (None, None)
        support.invalidate(uuid4())
    assert "secret-redis-password" not in caplog.text
    assert "private-user-identity" not in caplog.text
    assert "quota_unavailable" in caplog.text and "cache_unavailable" in caplog.text
    assert support.client.eval.call_count == 3


def test_disabled_features_do_not_connect(settings):
    support = RedisSupport(settings)
    support.client = MagicMock()
    support.quota("bootstrap", "identity", 1, required=True)
    assert support.lookup(uuid4()) == (None, None)
    support.invalidate(uuid4())
    support.client.eval.assert_not_called()
    support.client.delete.assert_not_called()


def test_application_lifecycle_disposes_both_resources_without_startup_ping(settings, monkeypatch):
    engine, support = MagicMock(), MagicMock()
    monkeypatch.setattr("csrs.main.create_database_engine", lambda _: engine)
    monkeypatch.setattr("csrs.main.RedisSupport", lambda _: support)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        support.client.ping.assert_not_called()
        engine.connect.assert_not_called()
    support.close.assert_called_once()
    engine.dispose.assert_called_once()


def test_client_has_no_automatic_retries_and_finite_timeouts(settings):
    support = RedisSupport(settings)
    try:
        options = support.client.connection_pool.connection_kwargs
        assert options["socket_connect_timeout"] == 0.2
        assert options["socket_timeout"] == 0.2
        assert options["retry"].get_retries() == 0
        assert options["protocol"] == 2
    finally:
        support.close()


def test_database_disposal_survives_redis_cleanup_failure(settings, monkeypatch):
    engine, support = MagicMock(), MagicMock()
    support.close.side_effect = RuntimeError("cleanup failure")
    monkeypatch.setattr("csrs.main.create_database_engine", lambda _: engine)
    monkeypatch.setattr("csrs.main.RedisSupport", lambda _: support)
    with pytest.raises(RuntimeError, match="cleanup failure"), TestClient(create_app(settings)):
        pass
    engine.dispose.assert_called_once()


def test_blocked_os_dns_is_bounded_single_flight_and_does_not_block_shutdown(settings, monkeypatch):
    entered, release = Signal(), Signal()
    calls = []

    def blocked(*args):
        calls.append(args)
        entered.set()
        assert release.wait(5)
        raise socket.gaierror("test DNS unavailable")

    monkeypatch.setattr("csrs.redis_connection.socket.getaddrinfo", blocked)
    configuration = Settings(
        **(
            settings.model_dump()
            | {
                "redis_url": "redis://blocked.example:6379/0",
                "metadata_cache_enabled": True,
                "redis_connect_timeout_seconds": 0.05,
            }
        )
    )
    support = RedisSupport(configuration)
    try:
        started = monotonic()
        for _ in range(3):
            assert support.lookup(uuid4()) == (None, None)
        assert entered.is_set() and len(calls) == 1
        assert monotonic() - started < 1
        support.close()
        assert monotonic() - started < 1
    finally:
        release.set()
        assert support.resolver.pending.done.wait(5)
        support.close()


def test_resolver_success_cache_and_explicit_refresh(monkeypatch):
    calls = []

    def lookup(*args):
        calls.append(args)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 6379))]

    monkeypatch.setattr("csrs.redis_connection.socket.getaddrinfo", lookup)
    resolver = BoundedResolver()
    try:
        one = resolver.resolve("redis.example", 6379, 0, 1)
        assert resolver.resolve("redis.example", 6379, 0, 1) == one
        assert len(calls) == 1
        resolver.invalidate()
        assert resolver.resolve("redis.example", 6379, 0, 1) == one
        assert len(calls) == 2
    finally:
        resolver.close()


def test_tls_adapter_preserves_original_hostname_and_verification(settings):
    support = RedisSupport(
        Settings(**(settings.model_dump() | {"redis_url": "rediss://redis.example:6380/0"}))
    )
    try:
        connection = support.client.connection_pool.make_connection()
        assert isinstance(connection, BoundedSSLConnection)
        assert connection.host == "redis.example"
        assert connection.check_hostname and connection.cert_reqs == ssl.CERT_REQUIRED
    finally:
        support.close()
