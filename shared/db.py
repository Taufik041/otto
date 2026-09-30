from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect
from sqlmodel import Session as DbSession, create_engine

from shared import config

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_engine = None


def _make_engine(url):
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless asked; enforce them like Postgres does
        @event.listens_for(engine, "connect")
        def _fk_on(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
    return engine


def get_engine():
    global _engine
    if _engine is None:
        _engine = _make_engine(config.DATABASE_URL)
    return _engine


def alembic_config() -> Config:
    cfg = Config()  # alembic.ini is for the CLI; this works wherever the package is installed
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def init_db(url=None):
    """Migrate the database to the latest schema (alembic upgrade head). Connects, so it raises
    if the DB is unreachable."""
    global _engine
    if url is not None:
        _engine = _make_engine(url)
    engine = get_engine()
    have = inspect(engine).get_table_names()
    if "sessions" in have and "alembic_version" not in have:
        raise RuntimeError(
            "the database was created before Otto used migrations; reset it (see docs/dev.md): "
            "docker exec otto-pg psql -U otto -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public'")
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


@contextmanager
def get_db():
    """A session that commits on a clean exit and rolls back on an exception."""
    with DbSession(get_engine(), expire_on_commit=False) as s:
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
