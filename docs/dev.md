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

## How a chat turn runs

- **A follow-up is stored when it's posted.** `POST /sessions/{id}/messages` appends it as the
  next user `llm.message` event (with its seq, announced over NOTIFY). For a plain chat that gets a
  repo, this comes after `repo.attached`. Then the gateway wakes or creates the sandbox and queues
  the job. The worker continues from the stored message and doesn't add it again, so the
  conversation (`rebuild_messages`) has it exactly once.
- **A follow-up may switch the model.** `POST /sessions/{id}/messages` takes an optional
  `model` (a catalog id from `GET /models`). An unknown or unavailable one is a 400, with the
  same `detail` shape POST /sessions gives it, and changes nothing. A different one updates the
  session's model and appends `session.model_changed {from, to}` before the user message. The
  brain reads the session's model at every LLM call, and the history goes to the new model as it
  is (every provider speaks the same chat format).
- **Provider errors fail fast.** In `brain/providers.py`:
  - A real 429 cools the key down for the provider's own reset time (Retry-After,
    `x-ratelimit-reset-*`, OpenRouter's `X-RateLimit-Reset`), else 60s. The next key is tried at
    once, and a call's total waiting is capped at `MODEL_WAIT_BUDGET_SECONDS`.
  - Errors no wait fixes drop that key for the worker process at once (logged once, by index,
    never the key): 429 `insufficient_quota` and OpenRouter's 402 (`quota`), 401/403 (`auth`), and
    404, which drops the key for that model only (`model`).
  - With no key left, the turn ends `failed` with `error {stage: "model", reason}`, and
    `provider_health` records it, so `GET /models` shows the provider (or the model) unavailable
    with a hint until the gateway restarts. Until then, the gateway also refuses it with a 400
    (FastAPI's validation `detail`, with that `hint`) for a new chat (the model asked for, or the
    default it would get), a follow-up or a retry (the model asked for, or the chat's own).
  - Stop interrupts a model call within a second, whether it waits on a cooldown or on the request.
- **Chats title themselves once.** After a chat's first turn ends `done`, while its title is still
  its first message (`sessions.title_source = auto`), the brain gives it a better one: the PR
  proposal's title if the turn made one, else 3–6 words from the chat's own model. That's one short call
  with no tools, counted in usage. It's stored with `title_source = generated` and announced as
  `session.titled {title, source: "proposal" | "model"}`. A rename (`PATCH /sessions/{id}`) sets
  `title_source = user`, and is never replaced, even one made during the turn. If titling fails
  (the limit, the model), the chat keeps its title and the turn is unaffected.
- **Every agent turn ends with a deterministic finish** (`brain/loop.py`, `finish`). After the
  model's final message, and before the status becomes `done`, the brain does what the model left
  undone:
  - asks `git.status`
  - commits uncommitted changes, with a message from this turn's request
  - pushes when `otto/<id>` is ahead of the remote
  - with no PR yet, proposes one: `pr.proposed {title, body, head, base, additions, deletions,
    files, tests}`. The title is one short model call (no tools, counted in usage): imperative, at
    most 60 characters, written from the task, the model's final message and the changed files. If
    that call fails or hits the daily limit, the title is the trimmed task, and the turn is
    unaffected. The body is the model's final message, and the counts come from the push's
    diffstat. A newer proposal replaces older ones. Auto-titles use the proposal's title.
  - with a PR open, the push has updated it: `pr.updated {number, url, additions, deletions, files}`

  **Otto never opens a pull request itself.** The model has no `git_open_pr` tool, and the prompt
  tells it to commit and push and leave the PR to the user (the runner's `git.open_pr` handler
  remains, unused). The user opens the proposal with `POST /sessions/{id}/pr`, or declines it.

  These are ordinary bus actions, so each one is an event row. The finish is skipped for plain
  chats, stopped turns, and turns that ran nothing that could change the workspace (no edits,
  writes, commands or commits). A failed step records `error` with stage `finish` and `step` (the
  action that failed, e.g. `git.push`) and ends the turn `failed`; Retry runs it again. `git.status` needs a sandbox image with the current
  `runner/`; rebuild it after pulling (the image step of `scripts/dev_up.sh`). With an older
  image, the finish stops after the status check.

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
| `DAILY_TOKEN_LIMIT` | `300000` | A new user's daily token limit (UTC days). Existing users keep theirs (`users.daily_token_limit`); migration 0011 moved those still on the old default, 50000, to 300000. |
| `MODEL_PRICES` | `{}` | JSON `{"<model id>": {"input_per_1m": 0.15, "output_per_1m": 0.6}}` in USD, keyed by catalog id (`GET /models`). Unlisted models count as free. |
| `MODEL_WAIT_BUDGET_SECONDS` | `120` | A model call's total waiting on rate-limited keys (each wait is the provider's Retry-After / `x-ratelimit-reset-*`, else 60s). Past it, the call fails with "the model didn't respond". |
| `OTTO_LLM_TIMEOUT` | `120` | Seconds per model request before it counts as a failed try (long chat histories are slow). |
| `OTTO_MODELS` | built from the env | A JSON list of `{id, provider, model, label, description}` replacing the model catalog (`GET /models`). `description` is the one line under the model in the picker; an unavailable model (its provider has no key) gets a `hint` instead of being hidden. |
| `MAX_ACTIVE_SESSIONS` | `3` | Agent sessions (chats with a repo) one user may have at work at once (provisioning, queued or running). Plain chats don't count. |
| `MAX_ACTIVE_SANDBOXES` | `3` | The same, for everyone together: protects the cluster. Sandboxes kept warm between turns don't count; they exit after `SANDBOX_IDLE_MINUTES`. |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Origins allowed to call the API with credentials, to use the refresh cookie (`/auth/refresh`, `/auth/logout`; the gateway's own origin may too, for `/docs`), and to open the WebSocket. In production it defaults to `FRONTEND_URL`. |
| `OTTO_SIGNUP_MODE` | `open` (`allowlist` in production) | Who may make a new account: `open`, `allowlist` (`OTTO_ALLOWED_GITHUB`, `OTTO_ALLOWED_EMAILS`, approved access requests) or `closed`. Existing users always keep access. `OTTO_ACCEPTING=false` pauses every signup. See `docs/deploy.md`. |
| `RESEND_API_KEY` | none | Resend's key: password-reset links and "bring it back up" requests are emailed. Unset in development: printed to the console. Unset in production: no email ("Forgot password?" is hidden). |
| `OTTO_NOTIFY_TO` | none | The inbox "bring it back up" requests go to. |
| `EMAIL_FROM` | `Otto <noreply@taufi.dev>` | The sender. |
| `OTTO_SANDBOX_KUBECONFIG`, `OTTO_SANDBOX_NAMESPACE` | the default kubeconfig, `default` | The sandbox cluster. In development an unset kubeconfig means `~/.kube/config` (kind); in production it means the workers are offline. |

The production settings (`OTTO_ENV=production`), the remaining launch variables, the sandbox
cluster's RBAC and kubeconfig, and the rate limits are in [deploy.md](deploy.md).

`GITHUB_APP_ID` is the App's ID, and `GITHUB_APP_KEY_PATH` the path to its private key (a `.pem`;
`*.pem` and `otto-secrets/` are gitignored). `GITHUB_INSTALLATION_ID` is only the fallback for
`python -m orchestrator.cli create`; the gateway mints each sandbox's token for the installation
of the chat's repo.

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
- **Permissions:** repository contents and pull requests read & write, metadata read.
- **Webhook:** off (uncheck "Active"); Otto doesn't use webhooks.
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
| `POST /auth/signup`, `POST /auth/login` | none (JSON) | `{access_token, token_type: "bearer", expires_in, user}` and the refresh cookie. A signup the signup mode refuses is 403 `{"error": "invite_only"}` (503 `{"error": "paused"}` while paused). Both are rate-limited per IP (429 `{"error": "rate_limited"}`, `Retry-After`). |
| `POST /auth/email-status` `{email}` | none | `{exists}`: whether to ask for a password next or for a name and password (email-first sign-in). Rate-limited per IP. |
| `POST /wake-requests` `{message?}` | user | the workers are offline: emails `OTTO_NOTIFY_TO` (the user is the reply-to). 202 `{ok: true}`; once an hour per user (429 after); 503 `email_unavailable` in production without `RESEND_API_KEY`; 502 `email_failed` (the try doesn't count). Without a key in development, the email is printed to the gateway's log. |
| `POST /access-requests` `{github_login?, email?, note?}` | none | asks for an account while signups are invite-only: 201 `{ok: true}`, the same for a repeat. Rate-limited per IP. `python -m scripts.access_requests` lists and approves them. |
| `GET /health` | none | `{status: "up" \| "paused", workers: "online" \| "offline", version, password_reset}` (`password_reset`: whether "Forgot password?" can email a link). While workers are offline, agent work (a new repo chat, a repo follow-up, a retry) is 503 `{"error": "workers_offline"}` with nothing created; plain chats work. |
| `POST /auth/token` | none (form: `username`=email, `password`) | the same, for Swagger's Authorize button and OAuth2 clients |
| `POST /auth/refresh` | refresh cookie | the same body, and a new refresh cookie |
| `POST /auth/logout` | refresh cookie | revokes this device's refresh token family, clears the cookie; no body needed |
| `POST /auth/logout-all` | Bearer | revokes every refresh token and voids every access token |
| `POST /me/password`, `POST /auth/reset` | Bearer / reset token | signs out every device, and signs this one in again (the same body as login) |
| `POST /sessions/{id}/ws-ticket` | Bearer, the session's owner | `{ticket}`: single use, 30 seconds, for `WS /sessions/{id}/ws?ticket=...&after_seq=N` |
| `POST /sessions/{id}/seen` `{seq}` | Bearer, the session's owner | the user saw the chat up to event `seq`: it never moves backwards, and is capped at the chat's last event. `GET /sessions` gives each chat an `attention`: `working` while Otto works, `done`/`failed` when the latest turn ended so (failed or interrupted) after the last seen event, else `null` (a stop the user made, seen, anything else). |
| `POST /sessions/{id}/pr` `{title?}` | Bearer, the session's owner | opens the chat's proposed PR on GitHub with the installation's token (no sandbox, no model), and appends `pr.opened`. 201; 200 with the existing one if a PR is already open for `otto/<id>` (double clicks, two tabs). 409 while Otto works or with nothing proposed; 502 with GitHub's reason if it refuses. |
| `POST /sessions/{id}/pr/decline` | Bearer, the session's owner | "Not now": appends `pr.declined`. The proposal stays, so `POST .../pr` still opens it later. 409 with nothing proposed. |
| `POST /sessions/{id}/retry` | Bearer, the session's owner | runs a `failed` or `interrupted` turn again from where it stopped, with no new message (409 otherwise); `{model}` retries on another model (`session.model_changed`; 400 if unavailable) |
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
   attaches the repo; the agent works in a sandbox, commits, pushes `otto/<id>` and proposes a PR
   (`pr.proposed` in the events). `POST /sessions/{id}/pr` opens it (`pr.opened`).
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

Without `RESEND_API_KEY` (the default in development), emails are printed to the gateway's
console instead of sent (`[email] not sent (no RESEND_API_KEY)`): the password-reset link, and
the app's "Ask Taufik to bring it up" request. `./scripts/dev_all.sh` puts that console in
`.logs/gateway.log`; the landing page's form prints to `.logs/landing.log`.
