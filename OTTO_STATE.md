# Otto: project state (24 Sep 2026)

> Handoff for a reviewer picking Otto up cold. Read this first, then `PLAN.md`
> (in the Claude Project as `CODING_AGENT_PLAN.md`). `PLAN.md` describes the
> target system. This file describes what exists today and where it differs
> from the plan.

---

## 1. What Otto is

Otto is a Devin-style autonomous cloud coding agent, built by one person. A user
connects a GitHub repo, describes a task, watches the agent work live, and gets a
pull request back.

- **Owner:** Taufik Khan, a backend/DevOps engineer (Python, FastAPI, SQLModel,
  Postgres, RabbitMQ, Docker, Kubernetes, Helm, ArgoCD, Terraform).
- **Purpose:** a portfolio project, not a product. The aim is architectural depth
  that holds up in an interview. **Decision:** finish the full build first, then
  start job applications with Otto as the centerpiece.
- **Repo:** `github.com/Taufik041/otto`. The benchmark repo is
  `github.com/Taufik041/otto_test`.
- **Origin:** a YouTube breakdown of Devin-style architecture (summarized in §16).
  Its main points are an external LLM "brain", an isolated sandbox per session, a
  message queue between them, a GitHub App with 1-hour installation tokens, and
  WebSocket streaming backed by a database.

---

## 2. Target architecture

```
Browser ──► [Ingress / one edge LB] ──► Gateway (FastAPI, N replicas)
                                           │  sessions API, WS replay, GitHub callback, token minting
                                           ├──► Postgres (sessions, session_events, installations, repo_memory)
                                           ├──► Orchestrator (k8s Service) ──► one k8s Job per session
                                           └──► RabbitMQ (k8s Service, single broker)
                                                   ▲                        ▲
                                 Brain workers ────┘                        └──── Runner (inside the Job pod)
                                 (LLM loop, worker pool)                          (dumb executor; /workspace = repo)
```

### Architecture rules (from PLAN.md; treated as non-negotiable)
1. Every component has its final shape from day one. Features are added as new
   pieces (new action kinds, handlers, event types, or entry points). Existing
   work is never torn out.
2. The Brain talks only to the Bus.
3. Only the Orchestrator talks to Kubernetes.
4. Only the Gateway talks to the browser.
5. Everything observable becomes a row in `session_events`, which is the source
   of truth.
6. Each session gets a fresh sandbox.
7. The sandbox never holds a permanent credential. It only gets a GitHub
   installation token (valid for at most 1 hour), injected at runtime.
8. No agent frameworks (LangChain, LangGraph, CrewAI, AutoGen). The loop is
   written directly against an SDK.
9. Every phase begins with a bare-metal test that defines "done".

### Bus contract (in use as raw dicts; `shared/models.py` Pydantic not yet used)
```json
action: {"session_id": "s1", "action_id": "<uuid4>", "kind": "shell.exec", "payload": {...}}
result: {"session_id": "s1", "action_id": "<same>", "kind": "shell.exec.result", "ok": true, "payload": {...}}
```
- Every handler payload has the shape `{exit_code, stdout, stderr}`, plus optional
  extras such as `total_lines`.
- `ok` means `payload.exit_code == 0`.
- **Queue names in code:** `otto.<sid>.actions` / `otto.<sid>.results`.
  PLAN.md says `actions.<sid>` / `results.<sid>`, so one of the two needs updating.

---

## 3. How it was built: the "scale model"

Taufik chose to build a **single-user scale model** first: the same load-bearing
boundaries as the target, with simple stand-ins wherever a part is meant to be
replaced later. The build climbed a ladder. One interface stayed constant
throughout: `run(cmd) -> {exit_code, stdout, stderr}`.

| Step | What | Status |
|---|---|---|
| 1 | Manual REPL that runs commands in the sandbox via `docker exec` | ✅ |
| 2 | LLM with a single `shell_exec` tool, using the same `run()` | ✅ First autonomous run |
| 2b | Full tool vocabulary, still over `docker exec` | ✅ Solved the benchmark bug |
| 3 | `run()` replaced by a RabbitMQ `bus_call`, with a separate runner process | ✅ Behaved the same as step 2b |
| 4 | Runner baked into the image, non-root, no volume mount | ✅ |
| 5 | Runner as a k8s Job on kind, with RabbitMQ inside the cluster | ✅ |
| 6 | Full agent loop: laptop brain → port-forwarded bus → pod runner | ✅ Fixed the bug inside the pod |
| 7 | Orchestrator creates the Job from Python (k8s client) | ✅ Create + poke. `destroy` not verified |

---

## 4. File inventory (reconstructed from the chat; check against the repo)

Most working code lives in `scripts/` as step files. It is not yet in the
`gateway/ orchestrator/ brain/ runner/ shared/` layout the plan calls for. The
repo was partly restarted "from scratch" after the original Phase 0 scaffold, so
check whether `pyproject.toml`, `shared/models.py` and CI still exist.

| File | Purpose |
|---|---|
| `otto.sh` | Early harness: `up/sh/down/ls` for kind pods, from before the image was baked. It has a readiness marker (`/tmp/otto-ready`). |
| `infra/sandbox.Dockerfile` | Three stages. `base`: python:3.12-slim + git, ripgrep, ca-certs. `full`: adds node/npm. `runner`: adds `pip install aio-pika pytest`, a `useradd -m -u 1000 otto`, runner code at `/app/runner.py` (root-owned, `chmod 555`), `/workspace` owned by otto, `USER otto`, `ENTRYPOINT /app/entrypoint.sh`. Built from the repo root with `--target runner`. Pushed as `taufik041/otto-sandbox:dev`. |
| `infra/entrypoint.sh` | Clones `REPO_URL` into `/workspace` if it isn't there already. If `GITHUB_TOKEN` is set, it uses `https://x-access-token:$TOKEN@...`. Then runs `pip install --user -e /workspace` (best effort) and `exec python /app/runner.py`. |
| `infra/rabbitmq.yml` | Deployment `rabbitmq:3-management` with **replicas: 1** (fixed from 3), plus a Service exposing 5672/15672. |
| `infra/runner-test.yml` | Hand-applied Job `otto-s1` with `backoffLimit: 0`, `ttlSecondsAfterFinished: 100`, env `BUS_URL`, `SESSION_ID`, `REPO_URL`. Replaced by the orchestrator. |
| `docker-compose.yml` | Local Postgres 16 + RabbitMQ, used before the move to kind. |
| `scripts/step1_1.py` | `run(cmd)` via `docker exec -w /workspace otto-sb sh -c`. |
| `scripts/step1.2.py` | In-process agent with the full toolset over `docker exec`. |
| `scripts/step1_3_runner.py` | **The runner:** handlers, registry and aio_pika consume loop. Baked into the image. |
| `scripts/step1_3_agent.py` | **The brain (scale model):** OpenAI-compatible tool loop over RabbitMQ. |
| `scripts/poke.py` | `python scripts/poke.py <kind> '<json>'` publishes one action and prints the matching result. This is the main debugging tool. |
| `scripts/gh_token.py` | GitHub App auth: RS256 JWT → installation token → list repos → branch, commit, PR. Hardcodes `REPO`. |
| `scripts/learn_tools.py` | Tool-use learning exercise with a fake `get_weather`. |
| `orchestrator/sandbox.py` | `create_sandbox(session_id, repo_url, token=None)` and `destroy_sandbox(session_id)`. Uses `kubernetes` with `load_kube_config()` and `BatchV1Api`. Job name `otto-<sid>`, `restart_policy=Never`, `backoff_limit=0`, `ttl_seconds_after_finished=100`, delete with `propagation_policy=Foreground`. |
| `.env` (gitignored) | `API_KEY` (OpenRouter), `GITHUB_APP_ID=4931166`, `GITHUB_INSTALLATION_ID=161390714`, `GITHUB_APP_KEY_PATH=~/otto-secrets/otto.pem`. |

### 4.1 Runner (`step1_3_runner.py`)
- Every handler has the signature `handler(payload) -> dict`.
- The registry is keyed by **dotted kind**.
- `_run` executes with `shell=True`, `cwd=/workspace`, a 60 s timeout, and caps
  stdout and stderr at 10 000 chars each.
- `_resolve` runs `realpath` and rejects any path outside `/workspace`.

| Kind | Behaviour |
|---|---|
| `shell.exec` | Runs `cmd`, with an optional `timeout`. |
| `fs.read` | If no `start_line` is given, it runs `wc -l`. Files over 400 lines return an error asking for a range. `end_line` defaults to `start + 200`. The read itself is `sed -n 'S,Ep'`. |
| `fs.write` | Writes through a base64 pipe. It **refuses** when the file already exists and the new content is under 50% of the old size, and tells the model to use `fs.replace` instead. |
| `fs.replace` | `old_str` must occur **exactly once**. Zero or multiple matches return an error that explains what to fix. The file is read with `cat` and written back through base64. |
| `code.search` | Runs `rg -n '<pattern>' \| head -51`. If there are more than 50 matches, it appends a note saying the list is truncated, is not a total count, and that `rg -c` gives the count. |
| `git.status` / `git.diff` | Plain git. |
| `git.commit` | Runs `git add -A && git -c user.email=otto@local -c user.name=Otto commit -m '<msg>'` with single quotes escaped. |

Consume loop:
- Connects with `connect_robust(BUS_URL)` and sets `prefetch_count=1`.
- Declares both queues as durable.
- Wraps each message in `msg.process()`, so it is acked when the block exits.
- An unknown kind or a handler exception becomes a result with `ok: false`. The
  loop never dies.

### 4.2 Brain (`step1_3_agent.py`)

**Provider and wiring**
- Uses `OpenAI(base_url="https://openrouter.ai/api/v1", api_key=env API_KEY)` with
  `MODEL="openrouter/free"`.
- `SID` comes from the `SESSION_ID` env var and defaults to `s1`.
- The RabbitMQ URL is hard-coded: `amqp://guest:guest@localhost/`.

**Tools and system prompt**
- 8 tools with underscore names (`shell_exec`, `fs_read`, `fs_write`,
  `fs_replace`, `code_search`, `git_status`, `git_diff`, `git_commit`).
- A `KIND` dict maps each tool name to its dotted kind.
- The system prompt tells the model to:
  1. Search first, then read slices of files.
  2. Edit with `fs_replace`; use `fs_write` only for new files.
  3. Read docs and respect code marked frozen or deprecated.
  4. **Always** run `python -m pytest -q` after edits.
  5. Commit and summarize once the tests are green.

**Loop and guards**
- An unknown tool name returns an error that lists the valid tools.
- JSON-parse errors and bus errors are returned to the model as data.
- Tool content is truncated to 20 000 chars.
- The loop is capped at 20 iterations.
- The assistant turn, with its `tool_calls`, is appended before the tool results,
  with one result per `tool_call_id`.

---

## 5. Benchmark repo: `Taufik041/otto_test` (originally "otto-gym")

The repo is a small inventory-pricing service (`src/inventory/`) built to force
multi-tool behaviour.

- **Bug:** `pricing.qualifies_for_bulk` uses `>`, but `docs/PRICING.md` says
  "ten units or more". This gives 2 failing and 7 passing tests. The fix is one
  character (`>=`), and the fix was verified.
- **Decoy:** `legacy_pricing.py` has functions with the same names. Its docstring
  and the pricing doc both say it is frozen.
- **Token trap:** `catalog.py` is 640 lines and trips the 400-line read cap.
- **Answer-key leak:** `TASKS.md` is the answer key, and the agent reads it.
  Remove it for honest runs.
- **Noise:** `git add -A` commits `src/inventory.egg-info/`. Add `*.egg-info/` to
  the repo's `.gitignore`.

### Observed runs
| Run | Result |
|---|---|
| Task 1: fix failing tests (via `docker exec`, via the bus, via a k8s pod) | Solved every time: one `fs_replace` and `9 passed`. It left the legacy module alone and cited the pricing doc as the reason. |
| Task 2: price of SKU-1337 and number of `bearings` products | First answer: **50, which was wrong**. The search had silently capped at 50. After the truncation notice was added, it answered **105, which is correct**. The price, 83.3, was right both times. |
| Task 1 with "investigate only, do not edit" | The model **ignored** the instruction and fixed and committed anyway. The instruction-following failure is in the model, not the system. |

### Free-model quirks seen
- Wrong parameter names (`command`, `old_string`).
- Hallucinated tools, such as `read`, and a name containing `</parameter`.
- Whole-file rewrites before `fs_replace` existed.
- One run truncated a file mid-edit, then repaired it itself: the commit message
  said "restore missing functions".

---

## 6. GitHub App

- The App is named **`ottoci`**, because "otto" was taken. PRs show up as
  `ottoci[bot]`.
- Permissions: Contents read/write, Pull requests read/write, Metadata read.
- Webhooks are off, and the App can only be installed on the owner's account.
- It is installed on `Taufik041/otto_test` only.
- The private key is at `~/otto-secrets/otto.pem` (chmod 600). It is never in
  git, an image, or a pod.
- **Proven end to end:**
  1. A JWT (`iat = now-60`, `exp = now+600`, `iss = app_id`).
  2. `POST /app/installations/{id}/access_tokens` returns a `ghs_…` token.
  3. `GET /installation/repositories` returns only `otto_test`.
  4. A branch, a commit made through the Contents API, and a PR opened by
     `ottoci[bot]`.

---

## 7. Decisions log

| Decision | Reasoning |
|---|---|
| The brain runs **outside** the sandbox. Only the dumb executor goes in the pod. | This is the multi-tenant, hosted inversion of Claude Code's model. Users can't inspect the loop, prompts or keys, and `runner.py` contains nothing secret. |
| The runner does git push and PR creation, using an **injected** short-lived token. | The checkout is already in the sandbox. The token lasts at most 1 hour and is scoped to one repo. It is injected per session and never baked into the image. The `.pem` never leaves the backend. |
| The runner runs as non-root, and `/app` is root-owned with `555` permissions. | A hijacked runner can't rewrite its own code. |
| Isolation comes from the container and runtime, never from filtering shell commands. | Guarding `cd` leaks and breaks real commands. The real walls are: gVisor/Kata `RuntimeClass` (later), NetworkPolicy, non-root, dropped capabilities, read-only rootfs, and resource limits. |
| One queue pair per session, with exactly one consumer. | Hit three times: stale runner containers, then 3 broker replicas round-robining connections. Both caused silent hangs. |
| RabbitMQ is a single-replica **Deployment**, not a StatefulSet. | Queues are ephemeral and one node is enough. Naive replicas give N separate brokers. High availability later means clustered quorum queues or a managed broker. |
| Sandboxes are k8s **Jobs**, with no ports and no Service. | The work is finite and per session, and nothing connects to a runner. |
| The Gateway is a FastAPI application layer, with an Ingress in front. | The Gateway owns state: sessions, events, orchestrator and bus calls, the WebSocket, and token minting. nginx and Ingress only move bytes. JWT validation could be decentralized, but the Gateway would still be needed. |
| Internal load balancing uses k8s Services. | Only the edge needs a provisioned load balancer. |
| The brain is **its own service**: a worker pool that consumes a start-session signal. | Chosen on 23 Sep over running the brain inside the Gateway. It matches the plan, and the Gateway never imports the LLM loop. |
| pytest is baked into the image. | Common tools belong in the image, not in per-session installs. |
| The LLM client is OpenAI-compatible, with the provider set in config. | This allows swapping between OpenRouter, Gemini, Groq and Claude. |
| Resume works as a fresh sandbox plus a clone of the branch plus a summary from the event log. | Sandboxes are disposable; the state lives in git and Postgres. |
| LSP, browser, and code-server are deferred to V2. The browser tab is a "coming soon" stub. | Keeps V1 scope tight. |
| Swarm is out of scope. | If it is ever built, it would be N sessions plus a coordinator, never N brains on one sandbox. |
| Helm is skipped for now. | Raw manifests are enough until there are several services. |

---

## 8. Mapping to PLAN.md phases

| Phase | Status |
|---|---|
| 0 Scaffold | Partial. The scaffold was generated, then the repo restarted with a leaner layout. |
| 1 Brain + runner, no cloud | ✅ Done in scale-model form. |
| 2 GitHub App + real PRs | Auth and a standalone PR work ✅. The agent can't yet open its own PR ❌. |
| 3 Orchestrator + k8s | Image ✅, Jobs on kind ✅, create from Python ✅. Still missing: destroy verification, token injection, connect retry, `POST /sessions`, token refresh, and hardening. |
| 4 WebSocket + UI | Not started. Only design work exists (§12). |
| 5–8 | Not started. |

Tags were suggested at each checkpoint. Run `git tag` to see which ones actually
exist:

- `v0-skeleton`
- `phase2-auth-works`
- `phase3-image-ready`
- `phase3-pods-work`
- `phase3-loop-through-k8s`
- `phase3-orchestrator`

---

## 9. Known issues and fixes (priority order)

1. **Parallel tool calls deadlock.** `bus_call` iterates the results queue and
   acks and drops any `action_id` that doesn't match. If the model emits two
   tool calls in one turn, the second result is consumed and lost, and that call
   waits forever.
   - **Fix:** one background consumer per session that resolves
     `pending[action_id]` futures.
2. **Silent data loss on large files.** `fs.replace` and `fs.read` read through
   `_run`, which caps output at 10 KB. A replace on a file over 10 KB would edit
   a truncated copy and write it back.
   - **Fix:** internal reads must be uncapped (use Python I/O); cap only what goes
     back to the model.
3. **The runner dies on a cold broker.** If RabbitMQ isn't accepting connections
   yet, `connect_robust` fails fast. With `restartPolicy: Never` and
   `backoffLimit: 0`, the pod then dies. This was seen with both a DNS error and
   `ECONNREFUSED`.
   - **Fix:** wrap the connect in a retry loop of about 30 attempts, 2 s apart.
4. **Shell interpolation of model text.**
   - Affected inputs: the `code.search` pattern, the `fs.read` path inside
     `sed`/`wc`, and `git.commit` (partly escaped).
   - A single quote in a pattern breaks the command, and the injection surface is
     real.
   - **Fix:** use argv lists (`subprocess.run([...])`) or native Python.
5. **The brain blocks the event loop.** `client.chat.completions.create` is
   synchronous inside async code. That is fine for one session, but it breaks a
   worker pool.
   - **Fix:** use `AsyncOpenAI` or `asyncio.to_thread`.
6. **`_resolve` prefix check.** `startswith("/workspace")` also accepts
   `/workspace2`.
   - **Fix:** compare against `WS + os.sep` or use `os.path.commonpath`.
7. **Queues are never deleted** on teardown, so stale actions replay when a
   runner reconnects.
   - **Fix:** delete the session's queues in `destroy_sandbox`, or set a queue
     TTL.
8. **No event log.** Nothing writes `session_events` yet. `emit()` was specced
   but never added.
9. **`destroy_sandbox` is not verified** end to end.
10. **Hard-coded config.** The brain hard-codes `localhost` for RabbitMQ and
    OpenRouter as the provider. Move both to env vars (`BUS_URL`,
    `OTTO_BASE_URL`, `OTTO_MODEL`, `OTTO_API_KEY`).
11. **Local testing traps.**
    - Zombie `kubectl port-forward` processes hold 5672.
    - A compose broker and a forwarded cluster broker can both answer on
      localhost.
    - **Rule:** run only one broker at a time, or forward to 5673.
12. **Model limits.** `openrouter/free` allows 50 requests per day, which is
    about 3 agent runs. Its instruction-following is weak. For real runs, use
    Gemini Flash (free tier) as primary and Groq as backup, or a paid model for
    demos.

---

## 10. Security notes

- An OpenRouter key was pasted into chat several times. **It has been rotated.**
  Secrets now come from `.env`. Keep `.env` and `*.pem` gitignored.
- The `.pem` stays on the backend only. The installation token is allowed in the
  pod, injected per session, and never baked into the image.
- Planned pod hardening:
  - `RuntimeClass` (gVisor/Kata)
  - `NetworkPolicy` (pod may reach the broker and GitHub only)
  - `runAsNonRoot`
  - `readOnlyRootFilesystem`, with an `emptyDir` mounted at `/workspace`
  - `allowPrivilegeEscalation: false`
  - drop ALL capabilities
  - CPU and memory limits
- Never enforce isolation from inside the pod.

---

## 11. Scaling notes (design only, not to be built now)

- 1M registered users does not mean 1M concurrent sandboxes. Design for
  thousands of concurrent sessions.
- Each session needs:
  - **1 sandbox pod**
  - **2 cheap queues** on a shared broker
  - **a slot in a brain worker pool**, not a brain pod of its own
- How each part scales:
  - The Gateway is stateless and scales by adding replicas.
  - Brain workers autoscale on queue depth (KEDA).
  - Sandboxes scale through the cluster autoscaler on pending pods.
- Biggest future wins:
  - a **warm sandbox pool** inside the orchestrator, to cut the 30–60 s cold start
  - idle timeouts and per-user quotas, to control cost
  - queued session starts, for backpressure
- Durability, in layers:
  - durable queues and persistent messages
  - consumer acks, so a crashed consumer's message is redelivered
  - quorum queues, so a broker node can be lost
  - the **Postgres event log as the source of truth**
- Postgres later: PgBouncer, read replicas, and partitioning `session_events`.
- A service mesh only if internal mTLS, retries, or observability become
  necessary.

---

## 12. Design and frontend

- **Briefs sent to Claude Design:** `otto-design-brief.md` and
  `apple-vibes-design-guide.md`. The second was exported from the portfolio
  project.
- **Layout:** three panels in the style of Devin:
  - chat on the left
  - a tabbed workspace in the center: Terminal, Editor with diff, Browser (a V2
    stub), and Plan
  - a live event stream with a PR card on the right
- **Look:** Apple-style restraint for the chrome, with monospace, syntax-colored
  code content as the one bold element.
- **Themes and stack:** full light and dark themes built on tokens; ShadCN and
  Tailwind.
- **Deferred:** the autoplay demo animation.
- **Unknown:** the status of the Design output. Check the Design session.
- **Real frontend:** Phase 4. It needs the Gateway and WebSocket first.

---

## 13. Next steps (agreed order)

1. **Gateway and DB only.** This was chosen for the next session.
   - FastAPI endpoints:
     - `POST /sessions`: create a row, then call `create_sandbox`. Later it will
       also publish a start-session message.
     - `GET /sessions/{id}`: return the session's status and events.
   - SQLModel tables:
     - `Session(id, repo_url, task, status, created_at)`
     - `SessionEvent(session_id, seq, ts, type, payload JSONB)`, with primary key
       `(session_id, seq)` (frozen schema)
   - Open question: should the Gateway use the compose Postgres on localhost or a
     Postgres inside kind?
2. **Brain as its own service.**
   - A worker consumes the start-session message and runs the loop.
   - It writes every LLM message, action and result to `session_events`.
   - Fix issues #1, #5 and #10 as part of this.
3. **The PR finale.**
   - The orchestrator injects a fresh installation token.
   - The runner gains `git.push` and `git.open_pr`, parsing owner and repo from
     `REPO_URL`.
   - The brain gains the two matching tools.
   - **Test:** task in, and a PR from `ottoci[bot]` comes out, with no laptop
     scripts.
4. **Restructure.** Move the scripts into `gateway/`, `orchestrator/`, `brain/`,
   `runner/` and `shared/`. Adopt `shared/models.py`. Update PLAN.md (queue
   names, phase status).
5. **Phase 4.** WebSocket replay and tail, a frontend built from the design, and
   GitHub OAuth login.
6. **Publish and apply.** A README with an architecture diagram, a recorded demo,
   and the hardening pass. Then start applying.

---

## 14. Ways of working

- Taufik **writes the code himself**. A reviewer should give specs and review
  what he pastes, and only hand over full files when he asks.
- Plain, functional Python with minimal abstraction.
- Each part starts with its test, and gets built only until that test passes.
- One step at a time. He pushes back on detours, so explain the *why*.
- He is budget-conscious: session limits are tight, and development uses free LLM
  tiers.

---

## 15. Review checklist (for Fable 5.1)

1. Compare the repo on disk against this file and PLAN.md. List every deviation:
   queue names, raw dicts versus `shared/models.py`, and file layout.
2. Audit `scripts/step1_3_runner.py` against issues #2, #3, #4 and #6 in §9. Look
   for any other quoting or path bugs.
3. Audit `scripts/step1_3_agent.py`:
   - message ordering
   - error-as-data handling
   - parallel tool calls (#1)
   - the blocking client (#5)
   - config (#10)
4. Audit `infra/` (Dockerfile, entrypoint, manifests) against the security notes
   in §10.
5. Audit `orchestrator/sandbox.py`:
   - propose the token injection and queue cleanup
   - propose a test for `destroy_sandbox`
6. Propose the concrete Gateway + Brain service split (§13 steps 1–2) without
   breaking Architecture Rule 1.
7. Flag anything that would embarrass the project in an interview demo.

---

## 16. Appendix: reference video summary

- **GitHub App, not PATs.**
  - A PAT breaks when the person who issued it leaves the organization.
  - Instead, the App's private key signs a JWT, which is exchanged for a 1-hour
    installation token.
  - That token is injected into the sandbox and refreshed by the backend.
- **Sandbox per session.**
  - Every session gets a fresh sandbox.
  - A sandbox is heavy, around 8 CPUs: the app, code-server and a headless
    browser streamed to the UI.
  - Custom base images (E2B-style) speed up startup.
- **The agent loop runs on an external cluster, never in the sandbox.** Users
  must not be able to reverse-engineer it.
- **Tool calls travel through queues.** The agent publishes to a queue; the
  sandbox pulls, executes, and publishes the output back.
- **The backend streams through a WebSocket.**
  - It listens to the sandbox's results and writes them to the database.
  - It streams terminal output, file changes and the agent's thoughts over the
    WebSocket.
- **Tooling:**
  - persistent shells (`create_new_shell`, `write_to_shell`)
  - LSP (definitions and references)
  - Playwright for browser checks
  - Fly.io deploys
- **After V1:** Sentry and Datadog triggers for autonomous remediation (an error
  spike leads to a sandbox, a fix, and a PR or revert).
