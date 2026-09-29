# Otto: project state (29 Sep 2026, tag `backend-v1`)

> Read this first, then `CODING_AGENT_PLAN.md`. This file describes what exists
> today. The plan describes the target.

## 1. What Otto is
Otto is a Devin-style autonomous cloud coding agent and a solo portfolio project
(owner: Taufik Khan). A user connects a GitHub repo and describes a task. An agent
then works in an isolated Kubernetes sandbox, and the result is a pull request
authored by the GitHub App `ottoci[bot]`. Sessions can be followed up and resumed
weeks later. The goal is to finish the full build, then apply for jobs with Otto
as the centerpiece.

## 2. Status

| Area | State |
|---|---|
| Brain / runner over RabbitMQ | ✅ |
| Runner image on kind (non-root, immutable `/app`) | ✅ |
| Orchestrator (k8s Jobs, token injection, CLI) | ✅ |
| Persistence (Postgres, lossless event log, resume) | ✅ |
| GitHub App PRs (push `otto/<sid>`, open or reuse PR) | ✅ |
| Gateway API + brain worker, concurrent sessions | ✅ |
| Warm sandboxes (reuse, idle exit, recreate) | ✅ |
| Hardening (empty LLM responses, missing args) | ✅ |
| WebSocket live stream | ❌ next |
| Frontend | ❌ design brief exists |
| Auth, token refresh, pod hardening, deploy | ❌ later |

Proven end to end on kind:
- two concurrent sessions, each with its own PR (#4, #5)
- a warm follow-up that reused the pod (`sandbox.reused`)
- an idle pod exiting at 5 min, then `sandbox.recreated` on the next follow-up, on the same PR
- DELETE giving status `stopped` and removing the pod

## 3. Architecture (as built)
```
POST /sessions ─► Gateway (FastAPI)
                   ├─ insert Session row + session.created event (Postgres)
                   ├─ orchestrator.create_sandbox(sid) ─► k8s Job otto-<sid>
                   │       (GITHUB_TOKEN minted per sandbox, activeDeadlineSeconds=3000)
                   └─ publish {"type":"start"} to otto.sessions
Brain worker (python -m brain.worker, prefetch 3)
   └─ LLM loop ── otto.<sid>.actions ──► Runner (in pod) ── otto.<sid>.results ──► brain
      writes every message / action / result to session_events
Runner: clone → checkout or create otto/<sid> → consume → idle 30 min → exit 0 → TTL removes Job
Follow-up: gateway pings the runner (5s)
   ├─ pong    → reuse the pod
   └─ no pong → purge queues + recreate the pod (resumes the branch)
   then publish {"type":"resume"}
```

Rules:
- The brain talks only to the bus and Postgres.
- Only the gateway and orchestrator touch k8s.
- Everything observable is a `session_events` row.
- The pod is disposable. Code survives on the `otto/<sid>` branch; the
  conversation survives in Postgres.

## 4. Code layout
```
shared/        config.py (all env vars), bus.py (queue names otto.<sid>.actions/results,
               make_action/result), db.py, models.py (Session, SessionEvent),
               events.py (append_event with redaction, load_events), sessions.py, github.py
runner/        handlers.py (shell, fs.read/write/replace, code.search, git.*,
               control.ping/shutdown), main.py (consume loop, connect retry, idle timeout)
brain/         tools.py, bus.py (one consumer + pending futures), loop.py (AsyncOpenAI,
               retry on 429 or empty response, arg validation), resume.py, main.py (CLI),
               worker.py
orchestrator/  sandbox.py (create/destroy/status), cli.py
gateway/       app.py (REST API), github_app.py (JWT → installation token)
infra/         sandbox.Dockerfile, entrypoint.sh, k8s/rabbitmq.yml, k8s/runner.yml (legacy)
scripts/       dev_up.sh, poke.py, gh_open_test_pr.py
tests/         ~200 tests, all fakes. Nothing needs network or k8s.
skeleton/      archived pre-restructure scripts. Do not edit.
```

## 5. Gateway API
- `POST /sessions {repo_url, task}` returns 201. It returns 429 above
  `MAX_ACTIVE_SESSIONS`, and 502 if the sandbox can't be created.
- `GET /sessions`
- `GET /sessions/{id}`: includes `work_branch`, `pr_url` and `sandbox_status`.
- `GET /sessions/{id}/events?after_seq=N`
- `POST /sessions/{id}/messages {text}`: a follow-up. Returns 202, or 409 if the
  session is already running.
- `DELETE /sessions/{id}`: sets status `stopped`, removes the pod and queues.

Session statuses: `provisioning`, `queued`, `running`, `done`, `failed`,
`interrupted`, `stopped`.

## 6. Running it
```bash
./scripts/dev_up.sh        # kind cluster, rabbitmq, postgres container, image build + load, port-forward 5672
uvicorn gateway.app:app --port 8000
python -m brain.worker
```

Config lives in `.env`:
- LLM: `OTTO_BASE_URL`, `OTTO_API_KEY`, `OTTO_MODEL`
- GitHub App: `GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`, `GITHUB_APP_KEY_PATH`
- Database: `DATABASE_URL`
- Sandbox tuning: `SANDBOX_IDLE_MINUTES`, `SANDBOX_MAX_AGE_SECONDS`
- Concurrency: `MAX_ACTIVE_SESSIONS`, `WORKER_CONCURRENCY`

Workflow after every Claude Code task:
1. `git status` and `git log`
2. `pytest -q`
3. Run the end-to-end check
4. Merge and tag

## 7. Known limits and next hardening
- **Pod age cap.** Pods are capped at 50 minutes so they die before the 1-hour
  token. There's no `auth.refresh` yet, so longer sessions are killed.
- **The token is visible inside the pod**, in the Job spec and `/proc/1/environ`.
  The target design: the runner returns a git bundle and the backend pushes, so no
  token ever enters the pod.
- **No API auth yet.** The session limit is enforced per gateway process, and the
  crash sweep only runs at gateway startup.
- **No pod hardening yet.** Still to do: gVisor RuntimeClass, NetworkPolicy,
  runAsNonRoot at pod level, read-only root filesystem, dropped capabilities.
- **LLM.** `openrouter/free` is flaky and rate-limited. Gemini Flash (free tier)
  is recommended.
- **Test repo noise.** `Taufik041/otto_test` still commits `src/inventory.egg-info/`;
  add `*.egg-info/` to its `.gitignore`.
- **No DB migrations.** `init_db` adds columns defensively; Alembic comes later.

## 8. Next: Phase 4
1. **WebSocket** `/sessions/{id}/ws`:
   - on connect, replay events after `after_seq`, then stream new ones live
   - the live feed comes from Postgres LISTEN/NOTIFY fired on each `append_event`,
     so every live event is also a DB row
   - subscribe before replaying, dedupe by `seq`, heartbeat pings
2. **Frontend.** Built from `otto-design-brief.md` + `apple-vibes-design-guide.md`:
   - three panels: chat, a tabbed workspace (Terminal / Editor+diff /
     Browser-stub / Plan), and a live event stream
   - light and dark themes; ShadCN + Tailwind
3. **README.** Architecture diagram and a recorded demo. Then apply for jobs.

## 9. Decisions log (short)
- **Brain outside the sandbox; runner is a dumb executor.** Users never see the
  prompts, keys or loop.
- **One session = one sandbox pod + its own queues + a slot in the worker pool.**
- **RabbitMQ runs as a single-replica Deployment.** Naive replicas mean separate
  brokers, so the two sides of a session can't see each other.
- **Postgres is the source of truth.** The broker is only the conveyor belt; the
  worker acks a session when it starts.
- **Warm sandboxes** are reused when possible, the runner exits itself when idle,
  Kubernetes TTL cleans up, and the gateway pings before reusing a pod.
- **Isolation is enforced by the container and runtime**, never by filtering
  shell commands.
- **No agent frameworks.**
- **Swarm is out of scope.**