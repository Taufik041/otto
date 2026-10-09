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
  In production it's the **sandbox node**, one k3s machine on the tailnet ("Sandbox node").
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
- a sandbox node: a second Ubuntu 24.04 machine for the sandboxes ("Sandbox node"), set up during
  step 3

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
    // GitHub Actions deploys over ssh; the sandbox node's runners reach RabbitMQ; the gateway
    // reaches the sandbox node's Kubernetes API
    { "action": "accept", "src": ["tag:ci"], "dst": ["tag:otto:22"] },
    { "action": "accept", "src": ["tag:sandbox"], "dst": ["tag:otto:5672"] },
    { "action": "accept", "src": ["tag:otto"], "dst": ["tag:sandbox:6443"] },
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

   It installs everything, joins the tailnet as `tag:otto`, and stops before the stack: `.env`
   is still empty. It prints the server's Tailscale address and its host key line. Keep both
   (step 7, and the sandbox node).
3. Fill in the stack's settings ("One server with compose", `.env.prod.example` explains each):

   ```sh
   sudo -u deploy nano /opt/otto/deploy/compose/.env
   ```

   - `RABBITMQ_BIND` is already set: the bootstrap put the server's Tailscale address there.
   - `RABBITMQ_RUNNER_PASSWORD`: `openssl rand -hex 24`. The sandbox node's runners log in with it.
   - `OTTO_SANDBOX_NAMESPACE=otto-sandboxes`, `OTTO_RUNNER_AMQP_SECRET=otto-runner-amqp`, and
     `MAX_ACTIVE_SANDBOXES=1` (a 2 GB sandbox node runs one sandbox at a time).
   - `CLOUDFLARE_TUNNEL_TOKEN` comes from step 4.
   - `OTTO_GITHUB_CALLBACK_URL=https://ottoci-api.taufi.dev/auth/github/callback`
4. Set up the sandbox node ("Sandbox node", "The EC2 test node"). It needs the server's
   Tailscale address and `RABBITMQ_RUNNER_PASSWORD`, and gives you `sandbox.kubeconfig`.
5. Put the two secret files in `/opt/otto/deploy/compose/secrets/`: `sandbox.kubeconfig` and
   `github-app.pem`. Paste each with `sudo tee`.
6. Run the bootstrap again. It fixes the files' owners, starts the stack, waits for `/health`,
   and creates RabbitMQ's `otto-runner` user:

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
  stack comes back the same way. `otto.service` waits up to two minutes for the Tailscale address
  (RabbitMQ binds to it), and tries again every 30 seconds if it never comes.

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
  - RabbitMQ listens on `RABBITMQ_BIND` (loopback by default). The bootstrap sets it to the
    server's Tailscale address, which the sandbox node's runners reach it on. Never set it to a
    public one.
  - The runners log in as their own RabbitMQ user, `otto-runner` (`RABBITMQ_RUNNER_PASSWORD`).
    It may use only the sessions' queues (`otto.<session>.actions` and `.results`), not
    `otto.sessions` or anything else. `deploy/compose/runner_user.sh` creates it, or updates its
    password; the bootstrap and every deploy run it.

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

The same workflow builds the **sandbox image** (`infra/sandbox.Dockerfile`, target `runner`) and
pushes `ghcr.io/taufik041/otto-sandbox:<commit sha>` and `:main`. In production, `SANDBOX_IMAGE`
defaults to `:main`. Make that package **public** once, after the first push: on GitHub, open
your profile → **Packages** → `otto-sandbox` → **Package settings** → **Change visibility** →
**Public**. The sandbox node then pulls it with no credentials. (If it stays private, give the
node's `setup.sh` `GHCR_USER` and `GHCR_TOKEN`.)

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
| `SANDBOX_IMAGE` | `ghcr.io/taufik041/otto-sandbox:main` | The default in production; CI builds it from `infra/sandbox.Dockerfile`. A commit's tag pins it. |
| `MAX_ACTIVE_SANDBOXES` | `1` | At most the sandbox node's `SANDBOX_SLOTS`. |
| `OTTO_WORKERS_CHECK_SECONDS` | `20` | The compose file's default (the code's is 30): a sandbox node that goes down shows as offline within 25 seconds. |

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
`OTTO_WORKERS_CHECK_SECONDS` (30; 20 in the compose file), and again right after a sandbox
couldn't be created. Each check gives up after 5 seconds. While the
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

On the sandbox node, `deploy/sandbox-node/setup.sh` does everything in this section ("Sandbox
node"). On another cluster, the same files apply.

### The namespace

`deploy/sandbox-node/manifests/namespace.yaml` makes `otto-sandboxes` with Pod Security
`restricted` enforced (sandboxes run as non-root with no privileges; the cluster enforces it), and
turns off the default service account's token.

Each sandbox Job runs the image's `otto` user (uid 1000, `OTTO_SANDBOX_UID`), with
`runAsNonRoot`, no privilege escalation, every capability dropped, the `RuntimeDefault` seccomp
profile, and no service-account token. Its CPU, memory and disk requests and limits come from
`OTTO_SANDBOX_*_REQUEST` / `_LIMIT`. A `ResourceQuota` on the namespace caps the total size of
all sandboxes (`MAX_ACTIVE_SANDBOXES` caps how many are at work), and a `LimitRange` refuses a
container bigger than one sandbox (`manifests/limits.yaml`). A `NetworkPolicy` closes every pod
to incoming connections and lets it out only to DNS, the server's RabbitMQ and the internet on
80/443 (`manifests/networkpolicy.yaml`; "Sandbox node", "Isolation").

### RBAC for the gateway

`deploy/sandbox-node/manifests/rbac.yaml`: a service account `otto-gateway`, and a Role bound to
it that may create, get, list and delete Jobs, get and list Pods, and get `pods/log` (only for
`python -m orchestrator.cli create`, which waits on the logs), in the namespace. On a cluster
other than the sandbox node:

    for f in namespace rbac; do
        sed 's/${SANDBOX_NAMESPACE}/otto-sandboxes/g' "deploy/sandbox-node/manifests/$f.yaml" | kubectl apply -f -
    done

It's a Role, not a ClusterRole: the gateway can't see or touch anything outside the namespace,
and it can't read Secrets. The runners' Jobs reference the RabbitMQ Secret, and the kubelet
resolves it, not the gateway.

### Minting the gateway's kubeconfig

`rbac.yaml` also gives the service account a long-lived token (the Secret `otto-gateway-token`).
`scripts/sandbox_kubeconfig.sh` prints a kubeconfig around it. Before printing, it checks that
the kubeconfig may create Jobs but may not read Secrets or look outside the namespace:

```sh
sudo bash scripts/sandbox_kubeconfig.sh > sandbox.kubeconfig                 # on the sandbox node
SANDBOX_API_SERVER=https://<api>:6443 bash scripts/sandbox_kubeconfig.sh > sandbox.kubeconfig   # elsewhere
```

Copy `sandbox.kubeconfig` to the gateway's host, readable only by the gateway's user. With the
compose file that's `deploy/compose/secrets/sandbox.kubeconfig`, and the compose file sets
`OTTO_SANDBOX_KUBECONFIG` to it. Elsewhere, set `OTTO_SANDBOX_KUBECONFIG` to its path. Either
way, set `OTTO_SANDBOX_NAMESPACE=otto-sandboxes`. To rotate the token, delete the
`otto-gateway-token` Secret, run `setup.sh` again (or re-apply `rbac.yaml`), then rebuild the
file.

The kubeconfig's server must be reachable from the gateway. Unset, unreadable or unreachable,
the workers show as offline and the gateway keeps serving plain chats.

### The runners' RabbitMQ URL

Runners reach RabbitMQ from inside the cluster, by a different address than the gateway's
`BUS_URL`, and as their own RabbitMQ user, `otto-runner` ("One server with compose"). The URL
goes in a Secret in the sandbox namespace. On the sandbox node, `setup.sh` makes it from
`RUNNER_AMQP_PASSWORD` and `SERVER_TS_IP`; elsewhere:

    printf 'amqp://otto-runner:%s@100.x.y.z:5672/' "$RABBITMQ_RUNNER_PASSWORD" \
        | kubectl create secret generic otto-runner-amqp -n otto-sandboxes --from-file=url=/dev/stdin

Set `OTTO_RUNNER_AMQP_SECRET=otto-runner-amqp` (and `OTTO_RUNNER_AMQP_SECRET_KEY` if the key
isn't `url`). Each Job's `BUS_URL` then comes from the Secret (`secretKeyRef`), and the URL never
appears in a Job spec. Without a Secret, `OTTO_RUNNER_AMQP_URL` is put in the Job as a plain
value, which is fine for kind.

## Sandbox node

`deploy/sandbox-node/` turns one Ubuntu 24.04 x86 machine into the sandbox cluster: a
single-node k3s, reachable only over Tailscale. The same scripts set up a cloud instance (first,
a temporary EC2 `t3.small`) and a laptop or desktop (later). Nothing in them assumes which.

`setup.sh` checks before it changes anything, so running it again is safe. It:

- adds a 2 GB swap file, if the machine has no swap
- checks that the machine is on the tailnet with `tag:sandbox`, and takes its Tailscale address
- installs k3s (`k3s-config.yaml`):
  - traefik, servicelb and metrics-server off
  - the API, the kubelet and the node's address on the Tailscale address only (in `tls-san` too)
  - host-gw networking, so there's no VXLAN port
  - swap allowed for the system (pods get none)
  - k3s waits for the Tailscale address at every boot (`sandbox-node wait-address`)
- applies `manifests/`: the namespace (Pod Security `restricted`), the quota and the limits, the
  NetworkPolicy, and the gateway's RBAC with its token
- makes the runners' RabbitMQ Secret (`otto-runner-amqp`), from `RUNNER_AMQP_PASSWORD`
- pulls the sandbox image, so the first session doesn't wait for it
- installs `sandbox-node` (`up`, `down`, `status`) and writes `/etc/otto/sandbox-node.env`

| Setting | Default | |
|---|---|---|
| `SERVER_TS_IP` | (required) | The server's Tailscale address (`tailscale ip -4` there; the bootstrap prints it). |
| `RUNNER_AMQP_PASSWORD` | | The server's `RABBITMQ_RUNNER_PASSWORD`. Needed on the first run, and when it changes. |
| `NODE_NAME` | the hostname | The Kubernetes node's name. |
| `SANDBOX_SLOTS` | `1` | Sandboxes at once. The quota is this many sandboxes; the server's `MAX_ACTIVE_SANDBOXES` must not be more. |
| `OTTO_SANDBOX_CPU_REQUEST` / `_LIMIT` | `200m` / `1` | One sandbox's size, as the gateway's variables of the same names. Keep the two in step: the namespace refuses a sandbox bigger than this. |
| `OTTO_SANDBOX_MEMORY_REQUEST` / `_LIMIT` | `300Mi` / `1Gi` | |
| `OTTO_SANDBOX_STORAGE_REQUEST` / `_LIMIT` | `1Gi` / `4Gi` | |
| `SANDBOX_IMAGE` | `ghcr.io/taufik041/otto-sandbox:main` | The image to pull ahead. |
| `SANDBOX_NAMESPACE`, `RUNNER_AMQP_SECRET` | `otto-sandboxes`, `otto-runner-amqp` | The server's `OTTO_SANDBOX_NAMESPACE` and `OTTO_RUNNER_AMQP_SECRET`. |
| `GHCR_USER`, `GHCR_TOKEN` | | Only if the sandbox image is private: k3s's pull credentials (`/etc/rancher/k3s/registries.yaml`). |
| `K3S_VERSION` | the stable channel | Pins k3s, or upgrades it on a later run (e.g. `v1.36.5+k3s1`). |

`sudo bash deploy/sandbox-node/setup.sh render` prints the k3s settings and the manifests without
changing anything.

### The tailnet policy

Add one rule to the policy from "Launch day" step 3. It's already in that snippet:

```jsonc
// the gateway, on the server, reaches the sandbox node's Kubernetes API
{ "action": "accept", "src": ["tag:otto"], "dst": ["tag:sandbox:6443"] },
```

`tag:sandbox` → `tag:otto:5672` (the runners to RabbitMQ) is already there. Nothing else: the
node can't reach the server's ssh or any other port, the server reaches only the node's API, and
`tag:ci` reaches only the server's ssh. Your own devices (`autogroup:admin`) reach both, to ssh in.

### Isolation

Every pod in `otto-sandboxes` gets `manifests/networkpolicy.yaml`:

- **in:** nothing.
- **out:**
  - DNS, to the cluster's CoreDNS only (not 8.8.8.8:53)
  - `SERVER_TS_IP:5672` (RabbitMQ)
  - the internet on TCP 80 and 443, except 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16,
    100.64.0.0/10 (the tailnet) and 169.254.0.0/16 (cloud metadata)

So a sandbox can't reach the instance metadata, the node's own addresses (on its LAN, its Docker
bridge, its Tailscale address), the k3s API (directly or as the `kubernetes` Service), other pods,
or the server's other ports. k3s's built-in policy controller enforces it (it's on unless k3s
runs with `--disable-network-policy`, which `setup.sh` never sets).

`scripts/check_isolation.sh` shows it:

- It starts throwaway pods: a probe and a listening "neighbour" in the namespace, and a control
  pod in a namespace without the policy.
- It listens on 443 on every address of the node.
- It probes from both the probe and the control pod, so each "blocked" is shown to be the
  policy's doing (the control pod reaches it) or noted as "not there either".
- Last, from the node itself, it checks the tailnet policy: the server's 5672 open; 22, 443 and
  8000 closed.

```sh
sudo bash scripts/check_isolation.sh     # ends "isolation: every check passed", exit status 0
```

### The EC2 test node

A temporary `t3.small` (2 GB, one sandbox at a time), until the laptop takes over.

1. **A Tailscale key**, in the admin console, under **Settings** → **Keys** → **Generate auth
   key**:
   - not reusable (single-use), **ephemeral**, pre-approved
   - **Tags:** `tag:sandbox`

   Ephemeral means that Tailscale removes the node by itself once it's been offline for a while
   (after you terminate it).
2. **Launch it** in **EC2** → **Launch instance**:
   1. **Name:** `otto-sandbox`.
   2. **Application and OS Images:** Ubuntu Server 24.04 LTS, 64-bit (x86).
   3. **Instance type:** `t3.small`.
   4. **Key pair:** "Proceed without a key pair". The user data below adds your ssh key, and you
      connect over Tailscale.
   5. **Network settings:** the `otto-no-inbound` security group (no inbound rules at all).
   6. **Configure storage:** 20 GiB, gp3.
   7. **Advanced details:**
      - **IAM instance profile:** none. Nothing on the node needs AWS, and that leaves nothing for
        a sandbox to steal.
      - **Credit specification:** **Standard**.
      - **Metadata accessible:** Enabled. **Metadata version:** V2 only (token required).
        **Metadata response hop limit:** 1, so nothing in a container (one network hop away) can
        get a token, even without the NetworkPolicy.
      - **User data** (the key, the address, your public key):

        ```sh
        #!/bin/bash
        # runs once, as root, at the first boot
        set -euo pipefail
        curl -fsSL https://tailscale.com/install.sh | sh
        tailscale up --auth-key='tskey-auth-...' --hostname=otto-sandbox --advertise-tags=tag:sandbox
        install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/.ssh
        echo 'ssh-ed25519 AAAA... you@your-machine' >> /home/ubuntu/.ssh/authorized_keys
        chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys
        chmod 600 /home/ubuntu/.ssh/authorized_keys
        ```

        Anything on the instance can read its user data from the metadata service. The key in it
        is single-use, and spent by the time anything else runs.
   8. Click **Launch instance**. In a minute or two, `otto-sandbox` shows up under **Machines**
      in Tailscale, tagged `tag:sandbox`.
3. **Copy the scripts over**, from your checkout:

   ```sh
   tar c deploy/sandbox-node scripts/sandbox_kubeconfig.sh scripts/check_isolation.sh \
     | ssh ubuntu@otto-sandbox 'mkdir -p otto && tar x -C otto'
   ```

4. **Set it up.** Read `RABBITMQ_RUNNER_PASSWORD` on the server (Session Manager: `sudo grep
   RABBITMQ_RUNNER_PASSWORD /opt/otto/deploy/compose/.env`), then on the node:

   ```sh
   ssh ubuntu@otto-sandbox
   cd otto
   read -rsp 'RABBITMQ_RUNNER_PASSWORD: ' P; echo
   sudo env SERVER_TS_IP=100.x.y.z RUNNER_AMQP_PASSWORD="$P" bash deploy/sandbox-node/setup.sh
   ```

   It takes a few minutes, most of it the image. A warning that nothing answers at
   `SERVER_TS_IP:5672` is expected while the server's stack isn't up yet.
5. **The gateway's kubeconfig.** On the node, `sudo bash scripts/sandbox_kubeconfig.sh` prints it
   (after checking its access: `create jobs: yes; get secrets: no; pods in kube-system: no`). On
   the server (Session Manager), paste it in:

   ```sh
   sudo tee /opt/otto/deploy/compose/secrets/sandbox.kubeconfig >/dev/null   # paste, then Ctrl-D
   sudo chown 10001:10001 /opt/otto/deploy/compose/secrets/sandbox.kubeconfig
   sudo chmod 400 /opt/otto/deploy/compose/secrets/sandbox.kubeconfig
   ```

   The compose file already points `OTTO_SANDBOX_KUBECONFIG` at it (`/run/otto/sandbox.kubeconfig`
   in the containers); don't set it in `.env`. Check that `.env` has `OTTO_SANDBOX_NAMESPACE`,
   `OTTO_RUNNER_AMQP_SECRET` and `MAX_ACTIVE_SANDBOXES` ("Launch day" step 3). Then restart the
   gateway and the worker, so that they read both:

   ```sh
   cd /opt/otto/deploy/compose
   sudo -u deploy docker compose -f docker-compose.prod.yml up -d --force-recreate gateway worker
   ```

   On launch day, the bootstrap's second run (step 3.6) does this.
6. **Check it:**
   - on the server, `curl -s 127.0.0.1:8000/health` says `"workers":"online"`
   - on the node, `sudo bash scripts/check_isolation.sh` passes, and `sudo sandbox-node status`
     shows the node Ready
   - a repo chat runs in a sandbox ("Launch day" step 8)
   - `sudo sandbox-node down`, and within 30 seconds `/health` says `"workers":"offline"` and the
     landing page says "Chat only". `sudo sandbox-node up` brings it back.
7. **Tear it down** when the laptop has taken over (or to stop paying for it):
   1. In **EC2**, select `otto-sandbox` → **Instance state** → **Terminate instance**. Its disk
      goes with it.
   2. Tailscale removes the ephemeral node by itself; or remove it now under **Machines**. The key
      was single-use: there's nothing to revoke.
   3. Until another node's kubeconfig is in place, the workers show as offline and plain chats
      keep working.

   Terminate it; don't stop it. Once Tailscale has removed a stopped ephemeral node, it can't
   rejoin: its key is spent.

### Moving to the laptop

The same steps, on Ubuntu Desktop 24.04 (x86), with these differences:

- **Tailscale:** install it (`curl -fsSL https://tailscale.com/install.sh | sh`), and join with a
  key that's single-use, pre-approved and tagged `tag:sandbox`, but **not ephemeral**. A laptop
  sleeps and moves between networks, and should stay on the tailnet when it does:

  ```sh
  sudo tailscale up --auth-key='tskey-auth-...' --hostname=otto-laptop --advertise-tags=tag:sandbox
  ```

  A tagged machine belongs to the tag, not to you. On the tailnet, this laptop can then reach only
  what `tag:sandbox` may (the server's 5672). Use a laptop that does nothing else.
- **Bigger limits:** give `setup.sh` more slots and bigger sandboxes, and the server the same
  numbers. On a 16 GB laptop, for example:

  ```sh
  sudo env SERVER_TS_IP=100.x.y.z RUNNER_AMQP_PASSWORD="$P" SANDBOX_SLOTS=3 \
       OTTO_SANDBOX_CPU_LIMIT=2 OTTO_SANDBOX_MEMORY_LIMIT=2Gi OTTO_SANDBOX_STORAGE_LIMIT=8Gi \
       bash deploy/sandbox-node/setup.sh
  ```

  Then, in the server's `.env`, set `MAX_ACTIVE_SANDBOXES=3`, `OTTO_SANDBOX_CPU_LIMIT=2`,
  `OTTO_SANDBOX_MEMORY_LIMIT=2Gi` and `OTTO_SANDBOX_STORAGE_LIMIT=8Gi`.
- **The kubeconfig** is new (a new cluster, address and token): step 5 again, then tear down the
  EC2 node.
- The tailnet policy doesn't change: the rules name tags, not machines.
- Ubuntu Desktop already has swap (`/swap.img`); `setup.sh` leaves it. Docker on the laptop is
  fine alongside k3s.
- Nothing listens on the laptop's Wi-Fi or LAN address: the API and the kubelet bind to the
  Tailscale address, kube-proxy's health port to loopback, and host-gw has no port.
- **Sleep:** `setup.sh` leaves power settings alone. To keep the node up with the lid closed, set
  `HandleLidSwitch=ignore` and `HandleLidSwitchExternalPower=ignore` in
  `/etc/systemd/logind.conf`, and turn off automatic suspend in Settings → Power. To rule out sleep
  entirely: `sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`.

### When the node sleeps or is down

- **The gateway** can't reach the API. Within 25 seconds (a cached answer lasts 20, a check gives
  up after 5), `/health` says `"workers":"offline"`:
  - the landing page says "Chat only"
  - plain chats keep working
  - a new agent chat, a follow-up in a repo chat, or a retry gets `503 workers_offline`, and
    the app offers "Ask Taufik to bring it up"
- **Sandboxes that were running:**
  - asleep, they're frozen, and carry on when the machine wakes
  - their Job's deadline (`SANDBOX_MAX_AGE_SECONDS`) and the 1-hour GitHub token keep counting
    while it sleeps, and the brain may have given up on the session meanwhile. After a long
    sleep, retry the chat.
  - `sandbox-node down` stops them at once
- **When it's back:**
  - Tailscale reconnects
  - k3s waits for the Tailscale address before it starts
  - the gateway sees the workers online at its next check (within 20 seconds)
- **`sandbox-node down` lasts:** it stops k3s at boot too, until `sandbox-node up`.
- **A different Wi-Fi network changes nothing:** k3s uses only the Tailscale address, which stays
  the same.
- **New image:** a node keeps its copy of `:main`. `sandbox-node up` refreshes it, or run
  `sudo k3s crictl pull ghcr.io/taufik041/otto-sandbox:main` after a runner change. You can also
  pin `SANDBOX_IMAGE` on the server to a commit's tag.

## Connections

The gateway and the brain workers retry their first RabbitMQ connection with backoff (1s,
doubling, at most 30s) until the broker answers, and then reconnect on their own. The gateway's
Postgres `LISTEN` connection (live events) reconnects the same way. A runner gives up after about
a minute without a broker, and its Job ends.

## Checklist

1. Postgres and RabbitMQ up; `DATABASE_URL` and `BUS_URL` set for the gateway and the workers (the
   compose file does both; see "One server with compose").
2. The sandbox node set up ("Sandbox node"): `setup.sh` (the namespace, its RBAC, the runners' AMQP
   Secret), the gateway's kubeconfig in `secrets/`, the tailnet rule `tag:otto` →
   `tag:sandbox:6443`, and `scripts/check_isolation.sh` passing.
3. The `otto-sandbox` package on GHCR made public (or the node given pull credentials), and
   `MAX_ACTIVE_SANDBOXES` at most the node's `SANDBOX_SLOTS`.
4. The GitHub App's callback URL set to the gateway's, and `OTTO_GITHUB_CALLBACK_URL`.
5. `OTTO_ENV=production`, `FRONTEND_URL`, `AUTH_SECRET`, the signup settings.
6. `curl https://ottoci-api.taufi.dev/health` says `"workers": "online"` and
   `"password_reset": true` (`RESEND_API_KEY` and `OTTO_NOTIFY_TO` set; "Email (Resend)").
7. A backup ran (`docker compose -f docker-compose.prod.yml exec backup backup_db.sh`) and its dump
   is in the bucket.
