# Deploying Otto

How the production setup fits together, what to set, and how to give the gateway a sandbox
cluster with only the access it needs. For local development, see `docs/dev.md`.

## The pieces

- **The web app** (`web/`), a static build, at `FRONTEND_URL`.
- **The gateway** (`uvicorn gateway.app:app`), the API, on its own host (e.g. `api.<domain>`),
  behind Cloudflare.
- **Brain workers** (`python -m brain.worker`), one or more. They talk only to RabbitMQ and
  Postgres.
- **Postgres** and **RabbitMQ**, reachable from the gateway and the workers.
- **The sandbox cluster**: a Kubernetes cluster (or just a namespace in one) where each agent
  chat gets a Job. The gateway reaches it with a kubeconfig. The runners in it reach RabbitMQ.
- **The GitHub App**: sign-in, installs, tokens for the sandboxes, and the pull requests.
- **Resend**, for email: password-reset links (from the gateway), and "bring it back up"
  requests (from the gateway, and from the landing page's `/api/wake` function). See "Email
  (Resend)".

The app and the API must be on the **same site** (subdomains of one registered domain, such as
`ottoci.taufi.dev` and `ottoci-api.taufi.dev`). The refresh cookie is a host-only cookie on the API
host, with `SameSite=Lax`, so the browser sends it to the API only from a same-site page.

## Launch day

The order to bring Otto up on one fresh Ubuntu 24.04 `t3.small` (x86) with no inbound ports. Every
step links to its details below. You need:

- an AWS account
- a Tailscale account (free)
- Cloudflare managing `taufi.dev`
- Vercel
- the GitHub App
- a Resend account with `taufi.dev` verified, and its two keys ("Email (Resend)")
- your sandbox cluster's kubeconfig ("The sandbox cluster")

### 1. An AWS budget alert

Before anything else bills:

1. In the AWS console, open **Billing and Cost Management**, then **Budgets**, then **Create
   budget**.
2. Choose **Use a template**, then **Monthly cost budget**.
3. Name it `otto`, and set the amount to what you'll accept (a `t3.small` with a 30 GB disk is
   about $20 a month).
4. Add your email, and click **Create budget**. It emails at 85% and 100% of the amount, and
   when the forecast passes it.

### 2. Launch the instance

In **EC2**, click **Launch instance**:

1. **Name:** `otto-prod`.
2. **Application and OS Images:** Ubuntu Server 24.04 LTS, 64-bit (x86).
3. **Instance type:** `t3.small`.
4. **Key pair:** "Proceed without a key pair". You'll connect through Session Manager, then
   Tailscale.
5. **Network settings:** click **Edit** and **Create security group**, named `otto-no-inbound`.
   Remove the SSH rule, so there are **no inbound rules** at all. Outbound stays open.
6. **Configure storage:** 30 GiB, gp3.
7. **Advanced details:**
   - **IAM instance profile:** a role with `AmazonSSMManagedInstanceCore`. Create one under
     **IAM** → **Roles** → **Create role** → **AWS service: EC2** if you haven't. This is what
     makes Session Manager work.
   - **Credit specification:** **Standard**, so CPU bursts can't add charges.
8. Click **Launch instance**.

### 3. Bootstrap

First, on your machine:

- **A deploy key** for GitHub Actions:

  ```sh
  ssh-keygen -t ed25519 -f otto-deploy -C github-actions -N ''
  ```

  `otto-deploy.pub` goes to the server; the private `otto-deploy` file becomes the
  `DEPLOY_SSH_KEY` secret.
- **In Tailscale's admin console**, under **Access controls**, add the tags and the rules (merge
  them into your policy):

  ```jsonc
  "tagOwners": { "tag:otto": ["autogroup:admin"], "tag:ci": ["autogroup:admin"], "tag:sandbox": ["autogroup:admin"] },
  "acls": [
    // GitHub Actions deploys over ssh; the sandbox cluster's runners reach RabbitMQ
    { "action": "accept", "src": ["tag:ci"], "dst": ["tag:otto:22"] },
    { "action": "accept", "src": ["tag:sandbox"], "dst": ["tag:otto:5672"] },
    // you, to everything (keep your existing rules)
    { "action": "accept", "src": ["autogroup:admin"], "dst": ["*:*"] },
  ],
  ```

  `tag:ci` must exist here before the OAuth client below can use it.

- **Still in Tailscale**, under **Settings** → **Keys** → **Generate auth key**, make the
  server's key:
  - not reusable, not ephemeral, pre-approved
  - **Tags:** `tag:otto` (a tagged node's key never expires)

Then, on the server:

1. Connect: **EC2** → the instance → **Connect** → **Session Manager** → **Connect**.
2. Download and run the bootstrap:

   ```sh
   curl -fsSLO https://raw.githubusercontent.com/Taufik041/otto/main/deploy/aws/bootstrap.sh
   sudo env TAILSCALE_AUTH_KEY=tskey-auth-... \
            DEPLOY_SSH_PUBLIC_KEY="ssh-ed25519 AAAA... github-actions" \
            bash bootstrap.sh
   ```

   It installs everything, and stops before the stack: `.env` is still empty. It prints the
   server's Tailscale address and its host key line. Keep both for step 7.
3. Fill in the stack's settings ("One server with compose", `.env.prod.example` explains each):

   ```sh
   sudo -u deploy nano /opt/otto/deploy/compose/.env
   ```

   - `RABBITMQ_BIND` is the server's Tailscale address (`tailscale ip -4`).
   - `CLOUDFLARE_TUNNEL_TOKEN` comes from step 4.
   - `OTTO_GITHUB_CALLBACK_URL=https://ottoci-api.taufi.dev/auth/github/callback`
4. Put the two secret files in `/opt/otto/deploy/compose/secrets/`: `sandbox.kubeconfig` and
   `github-app.pem`. Paste each with `sudo tee`.
5. Run the bootstrap again. It fixes the files' owners, starts the stack, and waits for
   `/health`:

   ```sh
   sudo bash bootstrap.sh
   ```

   If the `otto-backend` package on GHCR is private, add `GHCR_USER=Taufik041` and
   `GHCR_TOKEN=<a token with read:packages>` to that command.

From now on, `ssh deploy@otto-prod` works from any device on your tailnet.

### 4. The Cloudflare Tunnel (`ottoci-api.taufi.dev`)

1. In the Cloudflare dashboard, open **Zero Trust** → **Networks** → **Tunnels**, then
   **Create a tunnel**.
2. Choose **Cloudflared**, name it `otto-api`, and click **Save tunnel**.
3. Under **Install and run a connector**, choose **Docker**. The command shown ends in
   `--token eyJ...`: copy that long token (only the token).
4. On the server, put it in `.env` as `CLOUDFLARE_TUNNEL_TOKEN=eyJ...`, then restart the stack:
   `sudo systemctl restart otto`. Back in Cloudflare, the connector shows **Connected**; click
   **Next**.
5. **Route traffic** → **Public hostname**:
   - **Subdomain:** `ottoci-api`, **Domain:** `taufi.dev`, **Path:** empty.
   - **Service:** type **HTTP**, URL `gateway:8000`.
6. Click **Save tunnel**. Cloudflare creates the `ottoci-api` DNS record itself. It is proxied
   (orange), and it must stay that way.
7. Check from anywhere: `curl https://ottoci-api.taufi.dev/health` answers
   `{"status":"up",...}`.

### 5. The GitHub App's callback URL

On GitHub, open **Settings** → **Developer settings** → **GitHub Apps** → your App →
**Edit**:

1. Under **Callback URL**, put `https://ottoci-api.taufi.dev/auth/github/callback` **first**.
   Installs always come back to the first one. Keep `http://localhost:8000/...` below it for
   development.
2. Click **Save changes**.

### 6. Vercel

Create the two projects and their DNS records, as "The web app and the landing page
(Vercel)" describes, with the landing project's email variables (`RESEND_API_KEY`,
`OTTO_NOTIFY_TO`). Then check that `https://ottoci.taufi.dev` and `https://otto.taufi.dev`
load.

### 7. Deploys from GitHub Actions

In the repository on GitHub, open **Settings** → **Environments** → **New environment**, name
it `production`, and add its **secrets**:

| Secret | Value |
|---|---|
| `TS_OAUTH_CLIENT_ID` | A Tailscale OAuth client's ID (below) |
| `TS_OAUTH_SECRET` | That client's secret |
| `DEPLOY_HOST` | `otto-prod` (or its Tailscale address) |
| `DEPLOY_SSH_KEY` | The whole private key file `otto-deploy` from step 3 |
| `DEPLOY_KNOWN_HOSTS` | The host key line the bootstrap printed: `otto-prod,100.x.y.z ssh-ed25519 AAAA...` |

Make the OAuth client in Tailscale under **Settings** → **OAuth clients** → **Generate OAuth
client**: scope **Keys → Auth Keys: Write**, tag **`tag:ci`**. The deploy job uses it to mint an
ephemeral, pre-approved `tag:ci` key for each run, so unlike an auth key there is nothing that
expires after 90 days. The secret is shown once; put it straight into `TS_OAUTH_SECRET`. The
`tag:ci` rule from step 3 (only port 22 on `tag:otto`) is all such a node can reach.

You can also add **variables**: `DEPLOY_USER` (default `deploy`) and `HEALTH_URL` (default
`https://ottoci-api.taufi.dev/health`).

From then on, every push to `main` that changes the backend goes through two workflows:

1. `backend` tests the code and pushes the image.
2. `deploy` joins the tailnet, SSHes in, runs `deploy/aws/deploy.sh <sha>` (it pulls that
   commit's image, pins it in `.env` and restarts the stack), and checks that `/health` reports
   the new version through the tunnel.

To roll back, open **Actions** → **deploy** → **Run workflow**, and enter an earlier commit.

### 8. Smoke test

1. Open `https://otto.taufi.dev`. The status pill says **Live**, and the replay plays.
2. Click **Get started**, and sign up (or log in) on `ottoci.taufi.dev`.
3. Send a plain chat ("hello"). The reply comes in live.
4. In **Settings** → **GitHub**, connect GitHub, and install the App on a test repo.
5. Start a repo chat on it. The work block runs in a sandbox, then "Ready for review" →
   **Create pull request** → the PR opens on GitHub.
6. Back on the server: `curl -s 127.0.0.1:8000/health` says `"workers":"online"`, and `docker
   compose -f /opt/otto/deploy/compose/docker-compose.prod.yml ps` shows every service healthy.
7. Run a backup now, and see its dump in the bucket: `docker compose -f
   docker-compose.prod.yml exec backup backup_db.sh`.
8. Email: `curl -s https://ottoci-api.taufi.dev/health` says `"password_reset":true`. Log out,
   and use **Forgot password?**: the link arrives. Then send the landing page's form by hand
   (what the offline dialog posts); it answers `{"ok":true}`, the email reaches
   `OTTO_NOTIFY_TO`, and replying to it goes to the address in the form:

   ```sh
   curl -s https://otto.taufi.dev/api/wake -H 'Origin: https://otto.taufi.dev' \
     -H 'Content-Type: application/json' \
     -d "{\"email\":\"you@example.com\",\"message\":\"smoke test\",\"openedAt\":$(( $(date +%s) * 1000 - 10000 ))}"
   ```

### Stopping and starting the server

- **To pause Otto** (and most of its cost): in **EC2**, select the instance → **Instance state**
  → **Stop instance**.
  - While it's stopped, you pay only for its disk (about $2.40 a month for 30 GB).
  - Everything on the disk stays: the database, `.env` and the images.
  - The landing page says **Offline**, and Get started opens the offline dialog (the tunnel is
    down, so `/health` doesn't answer).
- **To start it again:** **Instance state** → **Start instance**.
  1. Ubuntu boots, and Tailscale rejoins with the same name and address.
  2. `otto.service` starts the stack, on the image pinned in `.env`.
  3. cloudflared reconnects, and the pill turns **Live** within a minute.
  4. The public IP changes. Nothing uses it.
- **Stopping only the stack**, with the server kept up: `sudo systemctl stop otto`, then
  `sudo systemctl start otto`.
- **Reboots:** unattended upgrades may reboot the server at 04:30 UTC for a security update. The
  stack comes back the same way.

## The web app and the landing page (Vercel)

Both sites build from `web/`, as two Vercel projects with the same root directory:

| Project | Domain | Build command | What it serves |
|---|---|---|---|
| `otto-app` | `ottoci.taufi.dev` | `npm run vercel:app` | The app: its routes get `index.html`; any other path is a real 404 (the app's own 404 page, status 404) |
| `otto-landing` | `otto.taufi.dev` | `npm run vercel:landing` | The landing page: `/` and its files; any other path is `404.html`, status 404 |

### How it's served

One `vercel.json` can't describe both sites, because the projects share the root directory. So
each build command builds its site, then writes Vercel's **Build Output API** folder
(`web/.vercel/output/`): the files, plus a `config.json` with the routes and headers.
`scripts/vercel-output.mjs` does this from `web/vercel/site.mjs`. Vercel serves that folder as it
is, so the project's Output Directory setting is ignored.

- **Routes:** the app's client-side routes (`APP_ROUTES`, kept in step with `src/App.tsx` by a
  test) rewrite to `index.html`. Everything else is a 404, including a missing `/assets/` file.
- **Security headers, on every response:**
  - `Content-Security-Policy`:
    - `connect-src` is the page itself and the API only (`https://` and `wss://` of
      `VITE_API_URL`).
    - Scripts are the site's own, plus its inline pre-paint script by its SHA-256 hash.
    - Images are the site's own, `data:`, and GitHub avatars.
    - `frame-ancestors 'none'`.
  - `Strict-Transport-Security: max-age=63072000; includeSubDomains`
  - `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy` and
    `Permissions-Policy`.
- **Caching:**
  - `/assets/*` (hashed names) are `public, max-age=31536000, immutable`.
  - HTML, favicons and every 404 are `public, max-age=0, must-revalidate`.
- **Locally:** `npm run preview` (the app, :4173) and `npm run preview:landing` (:4174) serve
  the builds with the same rules and headers (`previewPlugin`).

### Environment variables

They're read at build time. Set them for Production, and for Preview if you use preview
deployments.

| Variable | `otto-app` | `otto-landing` | Notes |
|---|---|---|---|
| `VITE_API_URL` | `https://ottoci-api.taufi.dev` | `https://ottoci-api.taufi.dev` | Required. The gateway; the CSP's only other origin. A production build without it fails. |
| `VITE_APP_URL` | | `https://ottoci.taufi.dev` | Where Get started and Log in go (`/login`), and the legal pages |
| `VITE_LANDING_URL` | `https://otto.taufi.dev` | | The app's links back (Close, Watch the demo, the logo on its public pages) |
| `VITE_STATUS_OVERRIDE` | | `auto` | `up` or `down` fixes the status pill without asking the gateway |
| `VITE_GOOGLE_AUTH` | `0` | | `1` shows "Continue with Google" (there's no Google sign-in behind it yet) |
| `VITE_LINKEDIN_URL` | | your profile's URL | The footer's LinkedIn link; hidden when unset |
| `VITE_DEMO_BOOKING_URL` | your booking page | your booking page | "Book a live demo": in the app's workers-offline notice, and in the landing page's offline dialog. Hidden when unset |

The landing project also runs one function, `POST /api/wake` (the offline dialog's "Bring it
back up" form; `web/vercel/wake.mjs`). It reads these at **run time**, so a change needs no
rebuild, only a redeploy. They're not `VITE_` variables, so they never reach the page:

| Variable (`otto-landing` only) | Value | Notes |
|---|---|---|
| `RESEND_API_KEY` | the `otto-landing` key | A Sending access key for `taufi.dev` ("Email (Resend)"). Without it, the form answers 503 and the dialog offers a `mailto:` instead. Mark it **Sensitive**. |
| `OTTO_NOTIFY_TO` | your inbox | Where requests go. The visitor is only the reply-to; nothing is ever sent to them. |
| `EMAIL_FROM` | `Otto <noreply@taufi.dev>` | Optional; that's the default. |

The function takes only same-origin JSON, ignores a filled honeypot field, refuses a form sent
less than 3 seconds after it opened, caps the message at 1000 characters, rejects any address
with a line break, list or display name, and allows 3 requests an hour per IP (best effort: the
count lives in one function instance's memory).

The gateway must agree with these:

- `FRONTEND_URL=https://ottoci.taufi.dev`
- `CORS_ORIGINS=https://ottoci.taufi.dev`
- `OTTO_LANDING_ORIGINS=https://otto.taufi.dev`
- `OTTO_GITHUB_CALLBACK_URL=https://ottoci-api.taufi.dev/auth/github/callback`

The app and the API are both under `taufi.dev`, so the refresh cookie works (same site).

### Creating the two projects

Do this once per project: first `otto-app`, then `otto-landing`.

1. On vercel.com, click **Add New…**, then **Project**.
2. Under **Import Git Repository**, choose `Taufik041/otto` and click **Import**.
3. On **Configure Project**:
   1. **Project Name:** `otto-app` (or `otto-landing`).
   2. **Framework Preset:** Other.
   3. **Root Directory:** click **Edit**, choose `web`, and click **Continue**.
   4. Open **Build and Output Settings** and turn on the override for **Build Command**:
      `npm run vercel:app` (or `npm run vercel:landing`). Leave **Output Directory** and
      **Install Command** as they are.
   5. Open **Environment Variables** and add that project's variables from the table above.
4. Click **Deploy**, and wait for it to finish.
5. Open the project's **Settings**, then **General**, and set **Node.js Version** to 22.x.
   (Optional: under **Git**, turn on skipping deployments when nothing in the root directory
   changed.)
6. Under **Settings** → **Domains**, add `ottoci.taufi.dev` (or `otto.taufi.dev`) and click
   **Add**. Vercel shows the DNS record it expects: a **CNAME** and its target. Note the target.
7. Add that record in Cloudflare (below). When **Settings** → **Domains** shows the domain as
   **Valid Configuration**, Vercel has issued its certificate.

### Cloudflare DNS

In the Cloudflare dashboard, open `taufi.dev`, then **DNS** → **Records** → **Add record**, once
per site:

| Type | Name | Target | Proxy status | TTL |
|---|---|---|---|---|
| CNAME | `ottoci` | the target Vercel showed (e.g. `cname.vercel-dns.com`) | **DNS only** (grey cloud) | Auto |
| CNAME | `otto` | the target Vercel showed for the landing project | **DNS only** (grey cloud) | Auto |

- **Keep both records grey (DNS only).** Vercel serves these sites with its own certificates
  and CDN. Proxying them through Cloudflare would put a second CDN in front, and can block
  Vercel from issuing or renewing the certificate.
- **Leave the API's record alone.** `ottoci-api` is not one of these: the Cloudflare Tunnel
  creates its record ("One server with compose"), and that one stays proxied.

### Checking a deployment

```sh
curl -sI https://ottoci.taufi.dev/c/anything | grep -iE "^HTTP|content-security|strict-transport"   # 200
curl -sI https://ottoci.taufi.dev/nope | head -1                                                     # 404
curl -sI https://otto.taufi.dev/nope | head -1                                                       # 404
```

## One server with compose

`deploy/compose/docker-compose.prod.yml` runs the whole backend on one 2 GB x86 server:

| Service | What | Memory limit |
|---|---|---|
| `gateway` | `otto-backend gateway`: the API; it migrates the database when it starts | 320 MiB |
| `worker` | `otto-backend worker`: a brain worker; it starts once the gateway is healthy | 448 MiB |
| `postgres` | Postgres 16, data in the `postgres` volume, small-server settings | 320 MiB |
| `rabbitmq` | RabbitMQ 3.13 (`rabbitmq.conf`: memory watermark, no guest) | 320 MiB |
| `cloudflared` | The Cloudflare Tunnel: the only way in | 96 MiB |
| `backup` | `scripts/backup_db.sh` nightly (cron) | 128 MiB |

- Every service restarts unless stopped, has a healthcheck (`backup` excepted), and keeps at most
  3 × 10 MB of logs.
- Nothing listens publicly:
  - Postgres has no port.
  - The gateway listens on the server's loopback only (`GATEWAY_PORT`, 8000), for checks.
  - RabbitMQ listens on `RABBITMQ_BIND` (loopback by default). Set that to the private (VPN)
    address the sandbox cluster's runners reach it on, and never to a public one.

### The image

`deploy/backend.Dockerfile` builds `otto-backend`: a virtualenv in a slim Python 3.12 image,
running as an unprivileged user (uid 10001). Its command picks the process:

    docker run otto-backend gateway             # uvicorn on :8000, migrating first
    docker run otto-backend worker
    docker run otto-backend access-requests [--all | approve <who>]

CI (`.github/workflows/backend.yml`) runs `pytest` on every push and pull request. On `main`, it
builds and pushes `ghcr.io/taufik041/otto-backend:<commit sha>` and `:main`. The compose file
runs `:main` unless `OTTO_IMAGE` pins a commit's tag. If the package is private, log the server in
once: `docker login ghcr.io` with a token that can read packages.

### Setting up the server

On AWS, `deploy/aws/bootstrap.sh` does all of this ("Launch day", step 3). By hand, on any
server with Docker:

```sh
git clone https://github.com/Taufik041/otto && cd otto/deploy/compose
cp .env.prod.example .env && chmod 600 .env   # fill it in: the uncommented lines are required
mkdir -p secrets
cp /path/to/sandbox.kubeconfig secrets/sandbox.kubeconfig   # "Minting the gateway's kubeconfig"
cp /path/to/app.private-key.pem secrets/github-app.pem
sudo chown -R 10001:10001 secrets && sudo chmod 700 secrets && sudo chmod 400 secrets/*
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps        # all healthy
curl -s http://127.0.0.1:8000/health
```

- **The tunnel:** in Cloudflare's Zero Trust dashboard, create a tunnel, put its token in
  `CLOUDFLARE_TUNNEL_TOKEN`, and add a public hostname (the API's, e.g. `ottoci-api.taufi.dev`) for the
  service `http://gateway:8000`. Set `OTTO_TRUST_PROXY=1`: every request comes through Cloudflare.
- **Updating:** `docker compose -f docker-compose.prod.yml pull && docker compose -f
  docker-compose.prod.yml up -d`. The gateway migrates when it starts. To roll back, set
  `OTTO_IMAGE` to an earlier commit's tag. A migration is only undone by hand (`alembic
  downgrade`).
- **Approving access:** `docker compose -f docker-compose.prod.yml exec gateway otto
  access-requests approve <who>`.

### Backups

The `backup` service (`deploy/backup/`: `pg_dump` 16, the aws CLI, cron) runs
`scripts/backup_db.sh` at 03:15 UTC (`BACKUP_CRON`).

- It writes a compressed custom-format dump to
  `s3://$BACKUP_S3_BUCKET/$BACKUP_S3_PREFIX/otto-<UTC time>.dump`.
- It deletes that prefix's dumps older than `BACKUP_KEEP_DAYS` (14), going by the time in their
  names.
- `AWS_ENDPOINT_URL` points it at an S3-compatible store instead of AWS.
- The S3 user needs `s3:PutObject`, `s3:ListBucket` and `s3:DeleteObject` on that prefix.

```sh
docker compose -f docker-compose.prod.yml exec backup backup_db.sh      # one now
# restore, into the running stack's database (stop the gateway and the worker first)
aws s3 cp s3://$BUCKET/otto/db/otto-20261008T031500Z.dump otto.dump
docker compose -f docker-compose.prod.yml exec -T postgres pg_restore --clean --if-exists --no-owner -U otto -d otto < otto.dump
```

## Production environment

Set `OTTO_ENV=production`. That turns on:

- `Secure` cookies (the refresh cookie and the GitHub sign-in nonces).
- `CORS_ORIGINS` defaulting to `FRONTEND_URL` instead of the localhost origins. The same list is
  the WebSocket's Origin check and the cookie routes' CSRF check.
- No `/docs`, `/redoc` or `/openapi.json` unless `OTTO_DOCS=1`.
- Invite-only signups by default (`OTTO_SIGNUP_MODE=allowlist`).
- A startup check: the gateway refuses to start unless `FRONTEND_URL` and every `CORS_ORIGINS`
  entry are `https://`.
- No fallback to the default kubeconfig: without `OTTO_SANDBOX_KUBECONFIG`, workers are offline.

The gateway's environment (the workers need `DATABASE_URL`, `BUS_URL`, the provider keys and
`OTTO_ENV`; `.env.example` describes every variable):

| Variable | Example | Notes |
|---|---|---|
| `OTTO_ENV` | `production` | |
| `AUTH_SECRET` | 48 random characters | `python -c 'import secrets; print(secrets.token_urlsafe(48))'` |
| `DATABASE_URL` | `postgresql+psycopg://otto:…@db:5432/otto` | Migrations run when the gateway starts. |
| `BUS_URL` | `amqp://otto:…@rabbitmq:5672/` | RabbitMQ as the gateway and the workers reach it. |
| `FRONTEND_URL` | `https://ottoci.taufi.dev` | GitHub sign-in ends here (`/auth/callback`), and reset links start here. |
| `CORS_ORIGINS` | `https://ottoci.taufi.dev` | Defaults to `FRONTEND_URL`. |
| `OTTO_LANDING_ORIGINS` | `https://otto.taufi.dev` | Only reads `GET /health`, for the landing page's status pill. |
| `RESEND_API_KEY` | the `otto-gateway` key | See "Email (Resend)". Without it, production sends no email: "Forgot password?" is hidden (`GET /health` says `"password_reset": false`), and the app's "Ask Taufik to bring it up" answers 503. |
| `OTTO_NOTIFY_TO` | your inbox | Where the app's "bring it back up" requests go. The user is the reply-to, never a recipient. One request per user an hour. |
| `EMAIL_FROM` | `Otto <noreply@taufi.dev>` | Optional; that's the default. Must be on the verified domain. |
| `OTTO_TRUST_PROXY` | `1` | Only when every request comes through Cloudflare: rate limits then use `CF-Connecting-IP`. |
| `OTTO_VERSION` | the git commit | Shown by `GET /health`. |
| `OTTO_SIGNUP_MODE` | `allowlist` | `open`, `allowlist` or `closed`. See "Signups". |
| `OTTO_ALLOWED_GITHUB`, `OTTO_ALLOWED_EMAILS` | `someone,another` | Who may sign up in `allowlist` mode. |
| `OTTO_ACCEPTING` | `true` | `false` pauses every signup; `GET /health` says `paused`. |
| `OTTO_GITHUB_CALLBACK_URL` | `https://ottoci-api.taufi.dev/auth/github/callback` | Must be one of the App's callback URLs. |
| `GITHUB_APP_ID`, `GITHUB_APP_KEY_PATH`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_APP_SLUG` | | As in `docs/dev.md`. |
| `OTTO_SANDBOX_KUBECONFIG` | `/etc/otto/sandbox.kubeconfig` | See "The sandbox cluster". |
| `OTTO_SANDBOX_NAMESPACE` | `otto-sandboxes` | |
| `OTTO_RUNNER_AMQP_SECRET` | `otto-runner-amqp` | A Secret in that namespace holding the runners' RabbitMQ URL. |
| `SANDBOX_IMAGE` | `taufik041/otto-sandbox:<tag>` | Built from `infra/sandbox.Dockerfile`. |

### The GitHub App

As in `docs/dev.md`, except that the **Callback URL** is the gateway's public one,
`https://ottoci-api.taufi.dev/auth/github/callback`. Keep `http://localhost:8000/auth/github/callback`
as a second callback URL if the same App serves development. `OTTO_GITHUB_CALLBACK_URL` picks the
production one for sign-in. Installs always come back to the App's first callback URL, so list
the production one first.

## Signups

`OTTO_SIGNUP_MODE` decides who may make a **new** account. Signing in to an existing account
always works, whatever the mode:

- `open`: anyone.
- `allowlist`: GitHub sign-ups whose login is in `OTTO_ALLOWED_GITHUB`, email sign-ups whose
  email is in `OTTO_ALLOWED_EMAILS`, and anyone with an approved access request. GitHub
  sign-ups are matched by login only, never by GitHub's email.
- `closed`: no one.

Everyone else gets `403 {"error": "invite_only"}` from `POST /auth/signup`. A GitHub sign-up
lands on `FRONTEND_URL/auth/callback?error=invite_only`. With `OTTO_ACCEPTING=false`, every new
account is refused with `503 {"error": "paused"}` (`?error=paused` for GitHub).

People can ask for access with `POST /access-requests {github_login or email, note}`. A repeat
request for the same login or email updates the first one. To see and approve requests:

    python -m scripts.access_requests              # pending, oldest first
    python -m scripts.access_requests --all
    python -m scripts.access_requests approve 12   # by id, GitHub login or email

## Rate limits

These are per client IP, in the gateway's memory (one gateway process). `limits.LIMITS` in
`gateway/limits.py` sets them:

| Route | Limit |
|---|---|
| `POST /auth/login` and `POST /auth/token` (together) | 10 a minute |
| `POST /auth/signup` | 5 an hour |
| `POST /auth/email-status` | 30 per 10 minutes |
| `POST /access-requests` | 5 an hour |

Over a limit, the answer is `429 {"error": "rate_limited"}` with `Retry-After`. Behind
Cloudflare, set `OTTO_TRUST_PROXY=1` so that each visitor gets their own limit. Without it,
every request seems to come from Cloudflare. Never set it when the gateway is reachable directly:
anyone could then pick their own IP.

## Health and offline workers

`GET /health` needs no sign-in:

    {"status": "up" | "paused", "workers": "online" | "offline", "version": "..."}

`workers` reports whether the sandbox cluster answers. It's checked at most every
`OTTO_WORKERS_CHECK_SECONDS` (30), and again right after a sandbox couldn't be created. While the
workers are offline, plain chats still work. A new agent chat, a follow-up in a repo chat
(or one that attaches a repo), and a retry of a repo chat get
`503 {"error": "workers_offline"}` at once, and nothing is created or stored.

## Email (Resend)

Otto sends email through Resend's HTTP API, from `noreply@taufi.dev`:

- **Password-reset links**, from the gateway, to the account's own address. They expire in
  1 hour. In development without a key, the gateway prints the email (and the link) to its log.
- **"Bring it back up" requests**, only ever to `OTTO_NOTIFY_TO`, with the asker as the
  reply-to. They come from the gateway (the app's workers-offline notice, signed in) and from
  the landing page's `/api/wake` function (the offline dialog, which works while the API is
  down). In development, both print the email instead (`.logs/gateway.log`,
  `.logs/landing.log`).

### Verifying `taufi.dev`

1. On resend.com, open **Domains** → **Add Domain**, enter `taufi.dev`, and pick a region.
2. Resend lists DNS records (a DKIM `TXT`, and an `MX` and an SPF `TXT` on its `send`
   subdomain). In the Cloudflare dashboard, open `taufi.dev` → **DNS** → **Records**, and add
   each one exactly as shown.
   - **Proxy status: DNS only (grey cloud).** `TXT` and `MX` records can't be proxied anyway;
     if Cloudflare offers the orange cloud on any of them, turn it off.
   - If `taufi.dev` already has an SPF record on the same name, merge Resend's `include:` into
     it; a name may have only one SPF record.
3. Back in Resend, click **Verify DNS Records**, and wait until the domain says **Verified**
   (usually minutes).

### Two keys

In Resend, open **API Keys** → **Create API Key** twice. Both get **Permission: Sending
access** and **Domain: `taufi.dev`**, so neither can read anything or send from another domain:

| Name | Goes to |
|---|---|
| `otto-gateway` | `RESEND_API_KEY` in the server's `.env` (`deploy/compose/.env.prod.example`) |
| `otto-landing` | `RESEND_API_KEY` in the Vercel `otto-landing` project (Production) |

Separate keys can be revoked separately: if the landing page's form is abused, revoke
`otto-landing` and password resets still work.

## The sandbox cluster

The gateway is the only part of Otto that touches Kubernetes. It needs to create, read, list
and delete Jobs, and to read and list Pods, in **one namespace**. The brain workers need no
cluster access.

### The namespace

    kubectl create namespace otto-sandboxes
    # sandboxes run as non-root with no privileges; have the cluster enforce it
    kubectl label namespace otto-sandboxes pod-security.kubernetes.io/enforce=restricted

Each sandbox Job runs the image's `otto` user (uid 1000, `OTTO_SANDBOX_UID`), with
`runAsNonRoot`, no privilege escalation, every capability dropped, the `RuntimeDefault` seccomp
profile, and no service-account token. Its CPU, memory and disk requests and limits come from
`OTTO_SANDBOX_*_REQUEST` / `_LIMIT`. A `ResourceQuota` on the namespace caps the total size of
all sandboxes (`MAX_ACTIVE_SANDBOXES` caps how many are at work).

### RBAC for the gateway

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: otto-gateway
  namespace: otto-sandboxes
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: otto-gateway
  namespace: otto-sandboxes
rules:
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["create", "get", "list", "delete"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["pods/log"]         # only for `python -m orchestrator.cli create`, which waits on the logs
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: otto-gateway
  namespace: otto-sandboxes
subjects:
- kind: ServiceAccount
  name: otto-gateway
  namespace: otto-sandboxes
roleRef:
  kind: Role
  name: otto-gateway
  apiGroup: rbac.authorization.k8s.io
```

It's a Role, not a ClusterRole: the gateway can't see or touch anything outside the namespace,
and it can't read Secrets. The runners' Jobs reference the RabbitMQ Secret, and the kubelet
resolves it, not the gateway.

### Minting the gateway's kubeconfig

Give the service account a long-lived token Secret, and build a kubeconfig around it:

```sh
NS=otto-sandboxes
kubectl apply -n $NS -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: otto-gateway-token
  annotations:
    kubernetes.io/service-account.name: otto-gateway
type: kubernetes.io/service-account-token
EOF

SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
kubectl get secret -n $NS otto-gateway-token -o jsonpath='{.data.ca\.crt}' | base64 -d > ca.crt
TOKEN=$(kubectl get secret -n $NS otto-gateway-token -o jsonpath='{.data.token}' | base64 -d)

KUBECONFIG=sandbox.kubeconfig kubectl config set-cluster sandbox --server="$SERVER" \
    --certificate-authority=ca.crt --embed-certs=true
KUBECONFIG=sandbox.kubeconfig kubectl config set-credentials otto-gateway --token="$TOKEN"
KUBECONFIG=sandbox.kubeconfig kubectl config set-context sandbox --cluster=sandbox \
    --user=otto-gateway --namespace=$NS
KUBECONFIG=sandbox.kubeconfig kubectl config use-context sandbox
rm ca.crt

# check: allowed, then refused
KUBECONFIG=sandbox.kubeconfig kubectl auth can-i create jobs -n $NS
KUBECONFIG=sandbox.kubeconfig kubectl auth can-i get secrets -n $NS
```

Copy `sandbox.kubeconfig` to the gateway's host (readable only by the gateway's user), and set
`OTTO_SANDBOX_KUBECONFIG` to its path and `OTTO_SANDBOX_NAMESPACE=otto-sandboxes`. To rotate the
token, delete and re-create the `otto-gateway-token` Secret, then rebuild the file.
(`kubectl create token otto-gateway -n $NS --duration=…` gives an expiring token instead,
if you'd rather renew it on a schedule.)

The kubeconfig's server must be reachable from the gateway. Unset, unreadable or unreachable,
the workers show as offline and the gateway keeps serving plain chats.

### The runners' RabbitMQ URL

Runners reach RabbitMQ from inside the cluster, often by a different address (and ideally a
different, narrower RabbitMQ user) than the gateway's `BUS_URL`. Put it in a Secret in the
sandbox namespace:

    kubectl create secret generic otto-runner-amqp -n otto-sandboxes \
        --from-literal=url='amqp://runner:…@100.x.y.z:5672/'

and set `OTTO_RUNNER_AMQP_SECRET=otto-runner-amqp` (and `OTTO_RUNNER_AMQP_SECRET_KEY` if the key
isn't `url`). Each Job's `BUS_URL` then comes from the Secret (`secretKeyRef`), and the URL never
appears in a Job spec. Without a Secret, `OTTO_RUNNER_AMQP_URL` is put in the Job as a plain
value, which is fine for kind.

## Connections

The gateway and the brain workers retry their first RabbitMQ connection with backoff (1s,
doubling, at most 30s) until the broker answers, and then reconnect on their own. The gateway's
Postgres `LISTEN` connection (live events) reconnects the same way. A runner gives up after about
a minute without a broker, and its Job ends.

## Checklist

1. Postgres and RabbitMQ up; `DATABASE_URL` and `BUS_URL` set for the gateway and the workers (the
   compose file does both; see "One server with compose").
2. The sandbox namespace, its RBAC, the gateway's kubeconfig, and the runners' AMQP Secret.
3. The sandbox image pushed, and `SANDBOX_IMAGE` set to it.
4. The GitHub App's callback URL set to the gateway's, and `OTTO_GITHUB_CALLBACK_URL`.
5. `OTTO_ENV=production`, `FRONTEND_URL`, `AUTH_SECRET`, the signup settings.
6. `curl https://ottoci-api.taufi.dev/health` says `"workers": "online"` and
   `"password_reset": true` (`RESEND_API_KEY` and `OTTO_NOTIFY_TO` set; "Email (Resend)").
7. A backup ran (`docker compose -f docker-compose.prod.yml exec backup backup_db.sh`) and its dump
   is in the bucket.
