"""Serialized, transactional local startup migration; never run per API process."""

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from csrs.config import Settings
from csrs.database import create_database_engine

# Database-scoped advisory lock shared by every invocation of this entry point.
MIGRATION_LOCK = 0x435352534D494752


def upgrade(engine: Engine) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with engine.begin() as connection:
        # Uses the configured statement timeout: fail visibly rather than race DDL.
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.check(config)


def main() -> int:
    engine = None
    try:
        engine = create_database_engine(Settings())
        upgrade(engine)
        print(json.dumps({"event": "migration_ready", "schema": "head", "drift": False}))
        return 0
    except Exception as error:
        # Driver/Alembic messages may contain connection details or SQL.
        print(json.dumps({"event": "migration_failed", "error_class": type(error).__name__}))
        print("Check PostgreSQL health, credentials, migration history, and competing migrations.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
