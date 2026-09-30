"""Alembic environment. init_db() hands over its own connection; the CLI connects to DATABASE_URL."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

import shared.models  # noqa: F401  registers the tables on SQLModel.metadata
from shared import config


def run(conn):
    # SQLite can't ALTER most things; batch mode rebuilds the table instead
    context.configure(connection=conn, target_metadata=SQLModel.metadata,
                      render_as_batch=conn.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


if context.config.config_file_name:  # the CLI, with alembic.ini
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)
if context.is_offline_mode():
    raise SystemExit("offline (--sql) migrations are not supported")
conn = context.config.attributes.get("connection")
if conn is not None:
    run(conn)
else:
    with create_engine(config.DATABASE_URL).begin() as conn:
        run(conn)
