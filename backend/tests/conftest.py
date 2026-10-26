"""Unit tests are isolated from local .env files and shell configuration."""

import os

import pytest

from csrs.config import Settings


@pytest.fixture(autouse=True)
def isolate_application_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CSRS_") and key not in {"CSRS_TEST_DATABASE_URL", "CSRS_TEST_REDIS_URL"}:
            monkeypatch.delenv(key)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://test:unit_only@127.0.0.1:1/csrs_test",
        redis_url="redis://127.0.0.1:1/0",
        db_connect_timeout_seconds=1,
        rate_limits_enabled=False,
        metadata_cache_enabled=False,
    )
