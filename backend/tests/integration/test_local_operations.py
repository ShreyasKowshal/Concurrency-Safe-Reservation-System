"""Local startup and fixture guards against real, generated PostgreSQL databases."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session
from test_event_transactions import wait_until_blocked

from csrs import migrate
from csrs.demo import identities, operate
from csrs.migrate import MIGRATION_LOCK, upgrade
from csrs.models import Event, Reservation, User

pytestmark = pytest.mark.integration


def test_recovery_prepare_failure_cleans_its_committed_fixtures(
    clean_engine, postgres_settings, monkeypatch
):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "recovery_fixture", Path(__file__).resolve().parents[2] / "scripts" / "smoke_recovery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def unavailable(*_args):
        raise RuntimeError("Controlled HTTP interruption")

    monkeypatch.setattr(module, "client", unavailable)
    with pytest.raises(RuntimeError, match="Controlled HTTP"):
        module.prepare(clean_engine, postgres_settings)
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(Event)) == 0


def test_startup_migration_rolls_back_if_drift_verification_fails(database_factory, monkeypatch):
    def reject(_config):
        raise RuntimeError("Controlled drift verification failure")

    with database_factory() as engine:
        with monkeypatch.context() as patch:
            patch.setattr(migrate.command, "check", reject)
            with pytest.raises(RuntimeError, match="Controlled"):
                upgrade(engine)
        with engine.connect() as connection:
            assert inspect(connection).get_table_names() == []
        upgrade(engine)
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0002_worker_expiry"
            )


def test_startup_migration_waits_for_database_lock_and_preserves_data(
    database_factory, password_hash
):
    with database_factory() as engine:
        upgrade(engine)
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users(normalized_email,password_hash) VALUES (:email,:hash)"),
                {"email": "persistent@example.com", "hash": password_hash},
            )
        with engine.connect() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
            transaction = blocker.begin()
            blocker.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
            pid = blocker.scalar(text("SELECT pg_backend_pid()"))
            future = pool.submit(upgrade, engine)
            try:
                wait_until_blocked(engine, pid)
                assert not future.done()
            finally:
                transaction.commit()
            future.result(timeout=10)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM users")) == 1
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0002_worker_expiry"
            )


def test_demo_is_idempotent_and_cleanup_preserves_unrelated_data(clean_engine, user_factory):
    unrelated = user_factory("keep@example.com")
    scope = uuid4()
    first = operate(clean_engine, scope, "prepare", "Private test fixture password!")
    second = operate(clean_engine, scope, "prepare")
    assert first == second
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 4
        assert db.scalar(select(func.count()).select_from(Event)) == 3
    operate(clean_engine, scope, "cleanup")
    operate(clean_engine, scope, "cleanup")
    with Session(clean_engine) as db:
        assert db.get(User, unrelated.id) is not None
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(Event)) == 0


@pytest.mark.parametrize("collision", ["id", "email"])
def test_demo_refuses_identity_collision(clean_engine, user_factory, collision):
    scope = uuid4()
    unrelated = user_factory("keep@example.com")
    with Session(clean_engine) as db, db.begin():
        row = db.get(User, unrelated.id)
        if collision == "id":
            row.id = identities(scope)["organizer"]
        else:
            row.normalized_email = f"demo-{scope.hex}-organizer@example.com"
    with pytest.raises(ValueError, match="collision"):
        operate(clean_engine, scope, "cleanup")
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_demo_refuses_cleanup_if_other_user_reserved_demo_event(clean_engine, user_factory):
    scope = uuid4()
    outsider = user_factory("outside@example.com")
    data = operate(clean_engine, scope, "prepare", "Private test fixture password!")
    from datetime import timedelta
    from uuid import UUID

    from csrs.auth.service import database_time

    with Session(clean_engine) as db, db.begin():
        event = db.get(Event, UUID(data["events"]["workshop"]))
        now = database_time(db)
        db.add(
            Reservation(
                event_id=event.id, user_id=outsider.id, hold_expires_at=now + timedelta(minutes=5)
            )
        )
        event.allocated_seats = 1
    with pytest.raises(ValueError, match="refusing cleanup"):
        operate(clean_engine, scope, "cleanup")
    with Session(clean_engine) as db:
        assert db.scalar(select(func.count()).select_from(Reservation)) == 1
        assert db.scalar(select(func.count()).select_from(User)) == 4
