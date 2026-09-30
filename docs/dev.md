# Developing Otto

## Database and migrations

The schema lives in `shared/models.py` and is changed only through Alembic migrations in
`shared/migrations/versions/`. The gateway, the brain worker and the brain CLI all call
`init_db()` at startup, which runs `alembic upgrade head`; nothing else creates tables.

    alembic upgrade head       # migrate DATABASE_URL (default: the otto-pg dev database)
    alembic current            # which revision the database is at
    alembic revision -m "add widgets"   # a new, empty migration; write upgrade()/downgrade() by hand

After changing a model, add a migration for it: `tests/test_migrations.py` fails while the
migrated schema and the models disagree. Migrations must also run on SQLite (the tests use it):
use `op.batch_alter_table(...)` to alter an existing table.

To check migrations on a scratch Postgres database (it is wiped):

    docker exec otto-pg psql -U otto -c 'CREATE DATABASE otto_migtest'
    OTTO_TEST_POSTGRES_URL=postgresql+psycopg://otto:otto@localhost:5432/otto_migtest pytest tests/test_migrations.py

### Resetting the dev database

A database created before migrations existed is refused at startup. Throwing the dev data away is
fine; with the `otto-pg` container from `scripts/dev_up.sh`:

    docker exec otto-pg psql -U otto -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public'
    alembic upgrade head       # or just start the gateway

Stop the gateway and workers first, since they hold connections.
