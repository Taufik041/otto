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

## Accounts, GitHub and usage

### Environment

| Variable | Default | What it's for |
|---|---|---|
| `AUTH_SECRET` | (required) | Signs login cookies and GitHub OAuth state. At least 32 characters: `python -c 'import secrets; print(secrets.token_urlsafe(48))'`. The gateway won't start without it. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | none | The GitHub App's user OAuth (App settings, "Client ID" and a generated client secret). Needed for GitHub sign-in and for connecting installations. |
| `GITHUB_APP_SLUG` | none | The App's name in `github.com/apps/<slug>`: `ottoci`. |
| `FRONTEND_URL` | `http://localhost:5173` | Where the GitHub callback sends the browser afterwards, and the base of password-reset links. An `https://` URL also makes the login cookie `Secure`. |
| `DAILY_TOKEN_LIMIT` | `50000` | A new user's daily token limit (UTC days). Existing users keep theirs (`users.daily_token_limit`). |
| `MODEL_PRICES` | `{}` | JSON `{"<model id>": {"input_per_1m": 0.15, "output_per_1m": 0.6}}` in USD, keyed by catalog id (`GET /models`). Unlisted models count as free. |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Origins allowed to call the API with credentials, and to open the WebSocket. |

`GITHUB_APP_ID` and `GITHUB_APP_KEY_PATH` are as before. `GITHUB_INSTALLATION_ID` is now only the
fallback for `python -m orchestrator.cli create`; the gateway mints each sandbox's token for the
installation of the chat's repo.

### The GitHub App's settings

In the App's settings on GitHub:

- **Callback URL:** `http://localhost:8000/auth/github/callback` (the gateway's URL in production).
- **Request user authorization (OAuth) during installation:** on. GitHub then sends installs and
  updates to the callback URL, with a `code`; the **Setup URL** is disabled, and there is none.
- **Redirect on update:** on, if GitHub offers it, so changes to the repo selection come back.
- **Expire user authorization tokens:** either; Otto uses the user token once and doesn't keep it.
- **Client secret:** generate one for `GITHUB_CLIENT_SECRET`.
- **Permissions:** as before (repository contents and pull requests read & write, metadata read).
  No account permissions are needed: Otto doesn't read the GitHub email.
- **Where can this App be installed:** "Any account" if other people will connect their repos.

### Trying it without a frontend

The API's own docs page, `http://localhost:8000/docs`, is same-origin, so the browser keeps the
login cookie and sends it on every "Try it out". Every write must be JSON, and the page sends a
JSON content type whenever there is a body.

1. `POST /auth/signup` with `{"name", "email", "password"}` (8+ characters).
2. Open `http://localhost:8000/auth/github/start` in the same browser tab. Signed in, this links
   GitHub to the account (signed out, it signs in, creating a GitHub-only user). GitHub then sends
   you to `FRONTEND_URL`, which won't load without a frontend. That's fine; go back to `/docs`.
3. Open `http://localhost:8000/github/install`, pick the repos, and come back the same way.
   `GET /github` shows the installation.
4. `GET /repos` lists the repos, e.g. `Taufik041/otto_test`.
5. `POST /sessions` with `{"message": "what is a closure?"}` is a plain chat;
   `GET /sessions/{id}/events` shows the reply once the worker has answered.
6. `POST /sessions/{id}/messages` with `{"text": "fix the failing tests", "repo": "Taufik041/otto_test"}`
   attaches the repo; the agent works in a sandbox and opens a PR (`pr.opened` in the events).
7. `GET /usage` shows the tokens.
8. Lower your limit, and the next message is a 429 `{"code": "daily_limit", ...}`:

       docker exec otto-pg psql -U otto -c "UPDATE users SET daily_token_limit = 100 WHERE email = 'you@example.com'"

Password reset links are printed to the gateway's console (`[auth] password reset for ...`) until
there is email.
