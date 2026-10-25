from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from csrs.config import Settings
from csrs.main import create_app


def test_liveness_does_not_connect_to_database(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = MagicMock()
    monkeypatch.setattr("csrs.main.create_database_engine", lambda _: engine)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert response.headers["cache-control"] == "no-store"
    engine.connect.assert_not_called()
    engine.dispose.assert_called_once()


def test_readiness_queries_database(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MagicMock()
    monkeypatch.setattr("csrs.main.create_database_engine", lambda _: engine)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependencies": {"postgresql": "up"}}
    connection = engine.connect.return_value.__enter__.return_value
    assert str(connection.execute.call_args.args[0]) == "SELECT 1"


def test_readiness_failure_is_safe_and_liveness_survives(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = MagicMock()
    engine.connect.side_effect = OperationalError("SELECT 1", {}, Exception("private-password"))
    monkeypatch.setattr("csrs.main.create_database_engine", lambda _: engine)
    with TestClient(create_app(settings)) as client:
        ready = client.get("/api/v1/health/ready")
        live = client.get("/api/v1/health/live")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "dependencies": {"postgresql": "down"}}
    assert ready.headers["cache-control"] == "no-store"
    assert "private-password" not in ready.text
    assert live.status_code == 200


def test_business_routes_are_not_implemented(settings: Settings) -> None:
    app = create_app(settings)
    assert set(app.openapi()["paths"]) == {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/auth/csrf",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
    }
