# Developing Otto

## The web app

The frontend is in `web/` (see `web/README.md`). With the gateway running on port 8000:

    cd web && npm install      # once
    cd web && npm run dev      # http://localhost:5173

It signs in with the access and refresh tokens described under "How sign-in works" below.
`npm test` runs its tests (no network) and `npm run build` type-checks and builds it.

To run a whole chat against this stack from the browser's side, with the gateway, a worker and
`npm run dev` up:

    cd web && OTTO_EMAIL=you@example.com OTTO_PASSWORD=... node scripts/e2e.mjs

The script signs in, starts "@otto_test two tests are failing...", waits for the PR card, sends a
follow-up, opens Changes and Terminal, and screenshots the chat at 1440px and 390px in light and
dark into `web/screenshots/e2e/`. It opens a real PR. After changing `runner/`, rebuild the
sandbox image (the image step of `scripts/dev_up.sh`), or sandboxes keep running the old code.

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
| `AUTH_SECRET` | (required) | Signs access tokens and GitHub OAuth state. At least 32 characters: `python -c 'import secrets; print(secrets.token_urlsafe(48))'`. The gateway won't start without it. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | none | The GitHub App's user OAuth (App settings, "Client ID" and a generated client secret). Needed for GitHub sign-in and for connecting installations. |
| `GITHUB_APP_SLUG` | none | The App's name in `github.com/apps/<slug>`: `ottoci`. |
| `ACCESS_TOKEN_MINUTES` | `15` | How long an access token (the Bearer JWT) lasts. |
| `REFRESH_TOKEN_DAYS` | `30` | How long a refresh token (the `otto_refresh` cookie) lasts unused; each refresh swaps it for a new one. Rows that expired over a week ago are deleted when the gateway starts. |
| `REFRESH_REUSE_GRACE_SECONDS` | `20` | How long a just-rotated refresh token may come back as a retry (a lost response, two tabs refreshing at once) instead of counting as theft. |
| `FRONTEND_URL` | `http://localhost:5173` | Where the GitHub callback sends the browser afterwards (`/auth/callback` after a sign-in), and the base of password-reset links. An `https://` URL also makes the cookies `Secure`. |
| `DAILY_TOKEN_LIMIT` | `50000` | A new user's daily token limit (UTC days). Existing users keep theirs (`users.daily_token_limit`). |
| `MODEL_PRICES` | `{}` | JSON `{"<model id>": {"input_per_1m": 0.15, "output_per_1m": 0.6}}` in USD, keyed by catalog id (`GET /models`). Unlisted models count as free. |
| `OTTO_MODELS` | built from the env | A JSON list of `{id, provider, model, label, description}` replacing the model catalog (`GET /models`). `description` is the one line under the model in the picker; an unavailable model (its provider has no key) gets a `hint` instead of being hidden. |
| `MAX_ACTIVE_SESSIONS` | `3` | Agent sessions (chats with a repo) one user may have at work at once (provisioning, queued or running). Plain chats don't count. |
| `MAX_ACTIVE_SANDBOXES` | `3` | The same, for everyone together: protects the cluster. Sandboxes kept warm between turns don't count; they exit after `SANDBOX_IDLE_MINUTES`. |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Origins allowed to call the API with credentials, to use the refresh cookie (`/auth/refresh`, `/auth/logout`; the gateway's own origin may too, for `/docs`), and to open the WebSocket. |

`GITHUB_APP_ID` and `GITHUB_APP_KEY_PATH` are as before. `GITHUB_INSTALLATION_ID` is now only the
fallback for `python -m orchestrator.cli create`; the gateway mints each sandbox's token for the
installation of the chat's repo.

### The GitHub App's settings

In the App's settings on GitHub:

- **Callback URL:** `http://localhost:8000/auth/github/callback` (the gateway's URL in production).
- **Request user authorization (OAuth) during installation:** on. GitHub then sends installs and
  updates to the callback URL, with a `code`; the **Setup URL** is disabled, and there is none.
- **Redirect on update:** on, if GitHub offers it, so changes to the repo selection come back.
  Changes made on github.com arrive without Otto's state: the gateway accepts them only for a
  signed-in user whose GitHub account can access the installation, and only refreshes its caches.
- **Expire user authorization tokens:** either; Otto uses the user token once and doesn't keep it.
- **Client secret:** generate one for `GITHUB_CLIENT_SECRET`.
- **Permissions:** as before (repository contents and pull requests read & write, metadata read).
  No account permissions are needed: Otto doesn't read the GitHub email.
- **Where can this App be installed:** "Any account" if other people will connect their repos.

### How sign-in works

- **Access token:** a JWT (HS256, `AUTH_SECRET`) that lasts `ACCESS_TOKEN_MINUTES`. Send it as
  `Authorization: Bearer <token>` on every API call. It carries the user's `token_version`, so
  `POST /auth/logout-all` and changing or resetting the password void every access token at once.
- **Refresh token:** an opaque random string in the `otto_refresh` cookie (httpOnly,
  SameSite=Lax, `Path=/auth`, `REFRESH_TOKEN_DAYS`), stored in `refresh_tokens` only as a sha256.
  `POST /auth/refresh` swaps it for a new one and returns a new access token. Presenting a
  refresh token that was already swapped out revokes its whole family (that sign-in, on every
  device holding a copy) and is a 401, with one exception: a token rotated less than
  `REFRESH_REUSE_GRACE_SECONDS` ago, in a family nobody logged out or caught reusing, is a retry.
  It gets a new token in the same family, and the family lives on. `refresh_tokens.revoked_reason`
  says why each token ended: `rotated`, `logout`, `reuse`, `password` or `logout_all`.
- No CSRF guard on the API: a cross-site page can't add an `Authorization` header. Only
  `/auth/refresh` and `/auth/logout` read the cookie; SameSite=Lax, `Path=/auth` and an `Origin`
  check (`CORS_ORIGINS` or the gateway itself) protect them.

| Endpoint | Auth | What it does |
|---|---|---|
| `POST /auth/signup`, `POST /auth/login` | none (JSON) | `{access_token, token_type: "bearer", expires_in, user}` and the refresh cookie |
| `POST /auth/token` | none (form: `username`=email, `password`) | the same, for Swagger's Authorize button and OAuth2 clients |
| `POST /auth/refresh` | refresh cookie | the same body, and a new refresh cookie |
| `POST /auth/logout` | refresh cookie | revokes this device's refresh token family, clears the cookie; no body needed |
| `POST /auth/logout-all` | Bearer | revokes every refresh token and voids every access token |
| `POST /me/password`, `POST /auth/reset` | Bearer / reset token | signs out every device, and signs this one in again (the same body as login) |
| `POST /sessions/{id}/ws-ticket` | Bearer, the session's owner | `{ticket}`: single use, 30 seconds, for `WS /sessions/{id}/ws?ticket=...&after_seq=N` |
| `POST /sessions/{id}/retry` | Bearer, the session's owner | runs a `failed` or `interrupted` turn again from where it stopped, with no new message (409 otherwise) |
| `POST /auth/github/url` `{mode: "signin" \| "link"}` | none; Bearer for `link` | `{url}` to send the browser to, and the state's nonce cookie |
| `POST /github/install-url` | Bearer | `{url}` to install the App, and the state's nonce cookie |
| `GET /auth/github/start` | none | redirects to GitHub to sign in (for typing into the address bar) |

The frontend keeps the access token in memory, calls `/auth/refresh` (with
`credentials: "include"`) on load and whenever it gets a 401, and opens the WebSocket with a fresh
ticket each time. The GitHub callback ends a sign-in at `FRONTEND_URL/auth/callback` with a new
refresh cookie; that page calls `/auth/refresh` to get its access token. (`web/src/api/client.ts`
does all this; with the web app running, signing in at `http://localhost:5173` is easier than the
/docs and curl routes below.) Cookies set by the API
(the refresh and nonce cookies) need the frontend and the API on the same site, as
`localhost:5173` and `localhost:8000` are.

### Trying it with /docs

1. Open `http://localhost:8000/docs`. `POST /auth/signup` with `{"name", "email", "password"}`
   (8+ characters), or skip it if you have an account.
2. Click **Authorize**. It offers two ways in; use either:
   - **OAuth2PasswordBearer:** the email as `username` and the password.
   - **HTTPBearer:** paste an access token (just the token, without `Bearer `).

   Every "Try it out" now sends the Bearer token: try `GET /me` and `GET /sessions`. The token
   lasts 15 minutes; authorize again (or `POST /auth/refresh`, and paste the new `access_token`
   into HTTPBearer) when you get a 401.
3. To link GitHub, open `http://localhost:8000/auth/github/start` in the same browser: the refresh
   cookie from step 2 tells the callback who you are, so it links GitHub to your account (signed
   out, it signs in, creating a GitHub-only user). GitHub then sends you to
   `FRONTEND_URL/auth/callback`, which won't load without a frontend. That's fine; go back to `/docs`.
4. `POST /github/install-url`, open the `url` it returns in the same browser, pick the repos, and
   come back the same way. `GET /github` shows the installation.
5. `GET /repos` lists the repos, e.g. `Taufik041/otto_test`.
6. `POST /sessions` with `{"message": "what is a closure?"}` is a plain chat;
   `GET /sessions/{id}/events` shows the reply once the worker has answered.
7. `POST /sessions/{id}/messages` with `{"text": "fix the failing tests", "repo": "Taufik041/otto_test"}`
   attaches the repo; the agent works in a sandbox and opens a PR (`pr.opened` in the events).
8. `GET /usage` shows the tokens.
   `POST /sessions/{id}/stop` stops a chat (and its sandbox); `POST /sessions/{id}/sandbox/stop`
   stops just the sandbox; `DELETE /sessions/{id}` deletes the chat and its events (its tokens
   still count toward the day).
9. Lower your limit, and the next message is a 429 `{"code": "daily_limit", ...}`:

       docker exec otto-pg psql -U otto -c "UPDATE users SET daily_token_limit = 100 WHERE email = 'you@example.com'"

10. `POST /auth/logout` (no body) signs this browser out: the refresh cookie is cleared and
    revoked. Click **Authorize** > **Logout** to drop the access token from the page too.

### A GitHub-only account in /docs

An account made by GitHub sign-in has no password, so the password form can't sign it in. Paste
a token instead:

1. Open `http://localhost:8000/auth/github/start` in the browser and sign in on GitHub. The
   callback sets the refresh cookie and sends you to `FRONTEND_URL/auth/callback`, which won't
   load without a frontend; that's fine.
2. Open `http://localhost:8000/docs` in the same browser and call `POST /auth/refresh` (no body,
   no authorization). The browser sends the refresh cookie, and the answer has an `access_token`.
3. Copy the `access_token`, click **Authorize**, paste it into **HTTPBearer**'s value, and
   **Authorize**. `GET /me` now shows the GitHub account.

### Trying it with curl

    B=http://localhost:8000
    curl -s -X POST $B/auth/login -H 'content-type: application/json' -c jar \
         -d '{"email": "you@example.com", "password": "your password"}'
    # copy access_token from the answer (or: TOKEN=$(... | jq -r .access_token))
    curl -s $B/me -H "Authorization: Bearer $TOKEN"
    curl -s $B/sessions -H "Authorization: Bearer $TOKEN"
    curl -s -X POST $B/auth/refresh -b jar -c jar      # a new access token, and a new cookie in jar
    curl -s -X POST $B/auth/logout -b jar -c jar

`-c jar` keeps the refresh cookie; without it, sign in again when the access token runs out.

Password reset links are printed to the gateway's console (`[auth] password reset for ...`) until
there is email.
