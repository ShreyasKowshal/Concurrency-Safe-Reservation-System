"""Each test run owns new disposable databases, never a development/shared schema."""

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from csrs.auth.crypto import hash_password
from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.main import create_app
from csrs.models import Role, User

BACKEND = Path(__file__).resolve().parents[2]
PASSWORD = "Correct horse battery staple 2026!"


def migration_config(connection) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["connection"] = connection
    return cfg


@pytest.fixture(scope="session")
def database_factory():
    value = os.environ.get("CSRS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set CSRS_TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test")
    url = make_url(value)
    if url.drivername != "postgresql+psycopg" or not (url.database or "").endswith("_test"):
        pytest.fail("Integration tests require postgresql+psycopg and a database ending in _test")
    admin = create_engine(
        url, isolation_level="AUTOCOMMIT", hide_parameters=True, connect_args={"connect_timeout": 5}
    )

    @contextmanager
    def create():
        # Identifier consists only of this fixed prefix/suffix and UUID hex generated here.
        name = "csrs_phase2_" + uuid.uuid4().hex + "_test"
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        settings = Settings(
            environment="test",
            database_url=url.set(database=name).render_as_string(hide_password=False),
            redis_url="redis://localhost:6379/0",
        )
        engine = create_database_engine(settings)
        try:
            yield engine
        finally:
            engine.dispose()
            assert name.startswith("csrs_phase2_") and name.endswith("_test")
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))

    try:
        yield create
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def migrated_engine(database_factory):
    with database_factory() as engine:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
        yield engine


@pytest.fixture
def postgres_settings(migrated_engine) -> Settings:
    return Settings(
        environment="test",
        database_url=migrated_engine.url.render_as_string(hide_password=False),
        redis_url="redis://localhost:6379/0",
    )


@pytest.fixture
def clean_engine(migrated_engine):
    assert migrated_engine.url.database.startswith("csrs_phase2_")
    with migrated_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE idempotency_records, reservations, events, sessions, users")
        )
    return migrated_engine


@pytest.fixture
def db(clean_engine):
    with Session(clean_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client_factory(clean_engine, postgres_settings):
    @contextmanager
    def create(settings=None, configure=None):
        app = create_app(settings or postgres_settings)
        if configure:
            configure(app)
        with TestClient(
            app,
            base_url="https://testserver"
            if (settings and settings.secure_cookies)
            else "http://testserver",
        ) as client:
            yield client

    return create


@pytest.fixture
def client(client_factory):
    with client_factory() as value:
        yield value


@pytest.fixture(scope="session")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def user_factory(clean_engine, password_hash):
    def create(email="attendee@example.com", role=Role.ATTENDEE, active=True):
        with Session(clean_engine, expire_on_commit=False) as db, db.begin():
            user = User(
                normalized_email=email, password_hash=password_hash, role=role, is_active=active
            )
            db.add(user)
            db.flush()
        return user

    return create
