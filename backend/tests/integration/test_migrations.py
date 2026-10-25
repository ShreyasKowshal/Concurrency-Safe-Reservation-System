import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from csrs.models import Base

pytestmark = pytest.mark.integration


def config(connection):
    from pathlib import Path

    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.attributes["connection"] = connection
    return cfg


def test_clean_upgrade_metadata_parity_and_non_destructive_reupgrade(
    database_factory, password_hash
):
    with database_factory() as engine:
        with engine.begin() as connection:
            assert inspect(connection).get_table_names() == []
            cfg = config(connection)
            command.upgrade(cfg, "head")
            assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {
                "alembic_version"
            }
            connection.execute(
                text(
                    "INSERT INTO users(normalized_email,password_hash) "
                    "VALUES ('migration@example.com',:hash)"
                ),
                {"hash": password_hash},
            )
            command.upgrade(cfg, "head")
            assert connection.scalar(text("SELECT count(*) FROM users")) == 1
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0001_foundation"
            )
            command.check(cfg)


def test_downgrade_and_reupgrade_only_on_disposable_database(database_factory):
    with database_factory() as engine:
        with engine.begin() as connection:
            cfg = config(connection)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "base")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
            command.upgrade(cfg, "head")
            assert set(Base.metadata.tables) <= set(inspect(connection).get_table_names())
