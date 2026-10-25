"""Opt-in PostgreSQL checks. Missing DSN skips; an invalid/unreachable DSN fails."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def postgres_settings() -> Settings:
    url = os.environ.get("CSRS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set CSRS_TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test")
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg" or not (parsed.database or "").endswith("_test"):
        pytest.fail("Integration tests require postgresql+psycopg and a database ending in _test")
    return Settings(environment="test", database_url=url, redis_url="redis://localhost:6379/0")


def test_readiness_against_real_postgresql(postgres_settings: Settings) -> None:
    with TestClient(create_app(postgres_settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependencies": {"postgresql": "up"}}


def test_database_is_postgresql_and_read_committed(postgres_settings: Settings) -> None:
    engine = create_database_engine(postgres_settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version()")).startswith("PostgreSQL")
            assert connection.scalar(text("SHOW transaction_isolation")) == "read committed"
    finally:
        engine.dispose()
