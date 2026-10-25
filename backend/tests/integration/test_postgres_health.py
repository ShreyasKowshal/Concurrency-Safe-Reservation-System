"""Opt-in PostgreSQL checks. Missing DSN skips; an invalid/unreachable DSN fails."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.main import create_app

pytestmark = pytest.mark.integration


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
