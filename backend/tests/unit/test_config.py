import pytest
from pydantic import ValidationError

from csrs.config import Settings


def test_connection_urls_are_required() -> None:
    with pytest.raises(ValidationError) as error:
        Settings()
    assert {item["loc"] for item in error.value.errors()} == {("database_url",), ("redis_url",)}


def test_environment_variables_are_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSRS_DATABASE_URL", "postgresql+psycopg://u:p@localhost/csrs_test")
    monkeypatch.setenv("CSRS_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("CSRS_ENVIRONMENT", "test")
    monkeypatch.setenv("CSRS_DB_POOL_SIZE", "2")
    settings = Settings()
    assert settings.environment == "test"
    assert settings.db_pool_size == 2


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///local.db",
        "postgresql://u:p@localhost/db",
        "not-a-url",
        "postgresql+psycopg:///db",
    ],
)
def test_only_explicit_postgresql_driver_is_allowed(settings: Settings, url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{**settings.model_dump(), "database_url": url})


@pytest.mark.parametrize("url", ["http://localhost", "redis:///0", "redis://localhost:0/0"])
def test_invalid_redis_url_is_rejected(settings: Settings, url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{**settings.model_dump(), "redis_url": url})


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://localhost/path",
        "http://u:p@localhost",
        "http://localhost?x=1",
        " http://localhost",
        "http://local\thost",
        "http://@localhost",
        "http://localhost?",
        "http://localhost#",
    ],
)
def test_public_origin_must_be_an_exact_origin(settings: Settings, origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{**settings.model_dump(), "public_origin": origin})


def test_production_requires_https(settings: Settings) -> None:
    with pytest.raises(ValidationError, match="requires HTTPS"):
        Settings(**{**settings.model_dump(), "environment": "production"})


@pytest.mark.parametrize("password", ["csrs_local_only", "csrs_test_local_only", "ci_example_only"])
def test_production_rejects_public_example_credentials(settings: Settings, password: str) -> None:
    with pytest.raises(ValidationError, match="replace public local examples") as error:
        Settings(
            **{
                **settings.model_dump(),
                "environment": "production",
                "public_origin": "https://reservations.example.com",
                "database_url": f"postgresql+psycopg://csrs:{password}@db/csrs",
            }
        )
    assert password not in str(error.value)


def test_invalid_pool_size_fails_early(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        Settings(**{**settings.model_dump(), "db_pool_size": 0})


def test_connection_secrets_are_redacted(settings: Settings) -> None:
    assert "unit_only" not in repr(settings)
    assert "unit_only" not in settings.model_dump_json()


def test_validation_error_does_not_print_connection_secret(settings: Settings) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(**{**settings.model_dump(), "database_url": "sqlite://secret-password"})
    assert "secret-password" not in str(error.value)
