from contextlib import contextmanager

from sqlalchemy import event, inspect, text
from sqlmodel import SQLModel, Session as DbSession, create_engine

from shared import config

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


def _add_missing_columns(engine):
    """Stand-in for migrations: add new nullable columns to tables that already exist."""
    existing = inspect(engine)
    q = engine.dialect.identifier_preparer.quote
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not existing.has_table(table.name):
                continue
            have = {c["name"] for c in existing.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                if not col.nullable:
                    raise RuntimeError(f"{table.name}.{col.name} is new and NOT NULL; "
                                       "recreate the dev database (no migrations yet)")
                conn.execute(text(f"ALTER TABLE {q(table.name)} ADD COLUMN {q(col.name)} "
                                  f"{col.type.compile(dialect=engine.dialect)}"))


def init_db(url=None):
    """Create the tables (no migrations yet). Connects, so it raises if the DB is unreachable."""
    global _engine
    if url is not None:
        _engine = _make_engine(url)
    import shared.models  # noqa: F401  registers the tables on SQLModel.metadata
    SQLModel.metadata.create_all(get_engine())
    _add_missing_columns(get_engine())


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
