import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel

from shared import db as shared_db
from shared.db import alembic_config, get_engine, head_revision, init_db
from shared.sessions import create_session, get_session

PG_URL = os.environ.get("OTTO_TEST_POSTGRES_URL")  # a scratch database; it is wiped


def version(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar()


def schema_diff(engine):
    with engine.connect() as c:
        return compare_metadata(MigrationContext.configure(c), SQLModel.metadata)


def test_init_db_migrates_a_fresh_database_to_head(db):
    engine = get_engine()
    assert {"sessions", "session_events", "alembic_version"} <= set(inspect(engine).get_table_names())
    assert version(engine) == head_revision()


def test_the_migrated_schema_matches_the_models(db):
    assert schema_diff(get_engine()) == []


def test_init_db_on_a_migrated_database_keeps_the_data(db):
    create_session("s1", task="t", repo_url=None, model="m")
    init_db()
    assert get_session("s1").task == "t"


def test_downgrade_to_base_and_back(db):
    engine = get_engine()
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    init_db()
    assert version(engine) == head_revision() and schema_diff(engine) == []


def test_a_database_made_before_migrations_is_refused(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    with create_engine(url).begin() as c:
        c.execute(text("CREATE TABLE sessions (id VARCHAR PRIMARY KEY)"))
    monkeypatch.setattr(shared_db, "_engine", None)
    with pytest.raises(RuntimeError, match="reset"):
        init_db(url)


@pytest.mark.skipif(not PG_URL, reason="set OTTO_TEST_POSTGRES_URL to a scratch Postgres database")
def test_postgres_upgrade_head_from_scratch(monkeypatch):
    engine = create_engine(PG_URL)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    monkeypatch.setattr(shared_db, "_engine", None)
    init_db(PG_URL)
    pg = get_engine()
    assert version(pg) == head_revision() and schema_diff(pg) == []
    cfg = alembic_config()
    with pg.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    init_db()
    assert version(pg) == head_revision()
    pg.dispose()
    engine.dispose()
