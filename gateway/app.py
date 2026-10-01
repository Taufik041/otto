"""Otto's HTTP API: accounts, GitHub, models, and chats (sessions): create, follow up, watch
events (also live, over a WebSocket), rename, stop.

    uvicorn gateway.app:app --port 8000

A chat with a repo ("owner/name", one of GET /repos) runs the agent in a sandbox; without one it
is a plain chat: no sandbox, and the model answers without tools. The gateway owns sandboxes (via
the orchestrator) and the session queues (via the bus); brain workers run the sessions it
enqueues on otto.sessions.
"""
import asyncio, json, re, uuid
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

import anyio
from aio_pika import DeliveryMode, Message, connect_robust
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel, Field, field_validator

from brain.bus import bus_call, start_consumer, stop_consumer
from gateway import auth, github_app, live, tokens
from orchestrator import sandbox
from shared import config, usage
from shared.accounts import delete_account
from shared.bus import SESSIONS_QUEUE, actions_queue, chat_job, resume_job, results_queue, start_job
from shared.db import get_engine, init_db
from shared.events import append_event, load_events, redact
from shared.models import User, as_utc, utcnow
from shared.sessions import (ACTIVE, attach_repo, count_active_agents, create_session, delete_session, get_session,
                             list_sessions, repo_sessions_since, set_status, set_title, sweep_stale_sessions,
                             transition)

PING_TIMEOUT = 5  # seconds to wait for a warm runner to answer control.ping / control.shutdown
PING_INTERVAL = 20  # seconds between WebSocket heartbeats
IDLE = ("pending", "done", "failed", "interrupted", "stopped", "limited")  # statuses that may take a follow-up
REPO_NAME = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
NEW_REPO = "Start a new chat for a different repo."


@asynccontextmanager
async def lifespan(app):
    auth.check_secret()
    init_db()
    swept = sweep_stale_sessions()
    if swept:
        print(f"[gateway] marked {len(swept)} stale session(s) interrupted: {', '.join(swept)}", flush=True)
    conn = await connect_robust(config.BUS_URL)
    listener = None
    try:
        engine = get_engine()
        if engine.dialect.name == "postgresql":
            listener = live.start(live.pg_url(engine.url))
        else:
            print("[gateway] not on Postgres: WebSockets replay events but get no live ones", flush=True)
        ch = await conn.channel()
        await ch.declare_queue(SESSIONS_QUEUE, durable=True)
        app.state.ch = ch
        app.state.create_lock = asyncio.Lock()
        yield
    finally:
        if listener:
            await live.stop(listener)
        await conn.close()


app = FastAPI(title="Otto", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(github_app.router)


# these don't read the login cookie: /auth/token takes a form, refresh and logout check the Origin
TOKEN_ROUTES = {"/auth/token", "/auth/refresh", "/auth/logout"}


@app.middleware("http")
async def json_only_writes(request: Request, call_next):
    """CSRF protection for the login cookie, alongside SameSite=Lax: a cross-site form can only
    send form or text bodies, and a cross-site fetch with a JSON content type needs a CORS
    preflight. Requests without that cookie (Bearer tokens, the refresh routes) don't need it."""
    bearer = request.headers.get("authorization", "").lower().startswith("bearer ")  # then the cookie is ignored
    cookie = auth.COOKIE in request.cookies and not bearer and request.url.path not in TOKEN_ROUTES
    if request.method not in ("GET", "HEAD", "OPTIONS") and cookie:
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return JSONResponse({"detail": "send state-changing requests as application/json"}, 415)
    return await call_next(request)


class DailyLimit(Exception):
    def __init__(self, info):
        self.info = info


@app.exception_handler(DailyLimit)
async def daily_limit(request: Request, e: DailyLimit):
    return JSONResponse({"code": "daily_limit", **e.info}, 429)


# added last, so it wraps everything above: refusals still carry CORS headers
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def repo_name(v):
    """"owner/name" (a leading @ is fine); ValueError (422) for anything else."""
    if v is None:
        return None
    v = v.strip().removeprefix("@")
    if not REPO_NAME.fullmatch(v):
        raise ValueError('repo must be "owner/name", as GET /repos lists it')
    return v


class NewSession(BaseModel):
    message: str = Field(min_length=1)
    repo: str | None = None  # "owner/name" from GET /repos; None: a plain chat
    model: str | None = None  # a catalog id (GET /models); None: the user's default, else the server's

    _repo = field_validator("repo")(repo_name)

    @field_validator("model")
    @classmethod
    def available_model(cls, v):
        if v is not None and not config.is_available(v):
            raise ValueError(f"unknown or unavailable model {v!r}; see GET /models")
        return v


class FollowUp(BaseModel):
    text: str = Field(min_length=1)
    repo: str | None = None  # attaches a repo to a plain chat; the chat's own repo is fine too
    model: str | None = None  # only to refuse it: a session stays on the model it was created with

    _repo = field_validator("repo")(repo_name)

    @field_validator("model")
    @classmethod
    def no_switching(cls, v):
        if v is not None:
            raise ValueError("a session's model is fixed at creation; start a new session for another model")
        return v


class Rename(BaseModel):
    title: str = Field(max_length=200)

    @field_validator("title")
    @classmethod
    def not_blank(cls, v):
        if not v.strip():
            raise ValueError("a title is required")
        return " ".join(v.split())


def new_session_id() -> str:
    return uuid.uuid4().hex[:10]  # lowercase alphanumerics: a valid k8s name


def _owned(row, user) -> bool:
    return row is not None and row.user_id is not None and row.user_id == user.id


def _row(sid, user):
    """The user's session; someone else's is 404 too, so ids reveal nothing."""
    row = get_session(sid)
    if not _owned(row, user):
        raise HTTPException(404, f"no session {sid!r}")
    return row


def _fail(sid, stage, e):
    """Record a provisioning error, mark the session failed, and answer 502."""
    msg = redact(f"{type(e).__name__}: {e}")[:2000]
    append_event(sid, "error", {"stage": stage, "message": msg})
    transition(sid, "failed", ACTIVE)
    raise HTTPException(502, f"{stage} failed: {msg}")


async def _enqueue(ch, sid, job):
    # queued BEFORE publishing, so a fast worker never sees a stale status
    transition(sid, "queued", {"provisioning"})
    try:
        await ch.default_exchange.publish(
            Message(json.dumps(job).encode(), delivery_mode=DeliveryMode.PERSISTENT),
            routing_key=SESSIONS_QUEUE)
    except Exception as e:
        _fail(sid, "enqueue", e)


async def _control(ch, sid, kind) -> dict:
    """Send a control action to the session's runner and wait briefly for its answer."""
    await ch.declare_queue(actions_queue(sid), durable=True)
    results = await ch.declare_queue(results_queue(sid), durable=True)
    pending, consumer = start_consumer(results)
    try:
        return await bus_call(ch, pending, sid, kind, {}, timeout=PING_TIMEOUT)
    finally:
        await stop_consumer(pending, consumer)


async def _queues(ch, sid):
    return [await ch.declare_queue(q, durable=True) for q in (actions_queue(sid), results_queue(sid))]


async def _status(sid) -> str:
    try:
        return await asyncio.to_thread(sandbox.sandbox_status, sid)
    except Exception as e:  # k8s unreachable: say so rather than fail the request
        print(f"[gateway] sandbox_status({sid}) failed: {e}", flush=True)
        return "unknown"


def _summary(row) -> dict:
    return {"id": row.id, "title": row.title, "status": row.status, "repo": row.repo, "model": row.model,
            "pr_url": row.pr_url, "updated_at": as_utc(row.updated_at)}


def _within_limit(user):
    """429 {"code": "daily_limit", "resets_at", "used", "limit"} once the user used today's tokens."""
    if info := usage.limit_status(user.id):
        raise DailyLimit(info)


def _model_for(user, asked) -> str:
    """The model a new session runs on: the one asked for, else the user's default (while it's
    available), else the server's."""
    mine = user.default_model if user.default_model and config.is_available(user.default_model) else None
    model = asked or mine or config.DEFAULT_MODEL
    if not config.is_available(model):
        raise HTTPException(503, f"default model {model!r} is not available: set OPENROUTER_API_KEY, "
                                 "or OPENAI_API_KEY with OTTO_OPENAI_MODELS (see GET /models)")
    return model


async def _repo_for(user, name) -> dict:
    """The user's repo called name, with its installation; 403 unless one of their installations
    can reach it."""
    found = await asyncio.to_thread(github_app.repo_access, user.id, name)
    if found is None:
        raise HTTPException(403, f"{name} isn't one of your repos: connect it on GitHub (GET /repos lists yours)")
    return found


def _room_for_an_agent(user):
    """429 unless the user, and the cluster, can take one more agent session at work. Plain chats
    have no sandbox and don't count. Call it under app.state.create_lock, with the claim."""
    if count_active_agents(user.id) >= config.MAX_ACTIVE_SESSIONS:
        raise HTTPException(429, f"you have {config.MAX_ACTIVE_SESSIONS} agent sessions at work already; "
                                 "wait for one to finish, or stop one")
    if count_active_agents() >= config.MAX_ACTIVE_SANDBOXES:
        raise HTTPException(429, f"all {config.MAX_ACTIVE_SANDBOXES} sandboxes are busy; try again in a few minutes")


async def _create_sandbox(sid, repo):
    await asyncio.to_thread(sandbox.create_sandbox, sid, f"https://github.com/{repo['full_name']}",
                            installation_id=repo["installation_id"])


@app.get("/models")
def models():
    """The model catalog for the frontend's picker; available: its provider has an API key."""
    return {"default_model": config.DEFAULT_MODEL,
            "models": [{"id": m["id"], "label": m["label"], "provider": m["provider"],
                        "available": config.is_available(m["id"])} for m in config.MODELS]}


@app.post("/sessions", status_code=201)
async def create(body: NewSession, user: User = Depends(auth.current_user)):
    """A new chat. With a repo, Otto works on it in a sandbox; without one, it just answers."""
    _within_limit(user)
    model = _model_for(user, body.model)
    repo = await _repo_for(user, body.repo) if body.repo else None
    async with app.state.create_lock:  # count + insert as one step within this gateway
        if repo:
            _room_for_an_agent(user)
        sid = new_session_id()
        row = create_session(sid, task=body.message, repo=repo["full_name"] if repo else None, model=model,
                             status="provisioning", user_id=user.id)
    if repo:
        try:
            await _create_sandbox(sid, repo)
        except Exception as e:
            _fail(sid, "create_sandbox", e)
    # the runner needn't be up yet: its actions wait in the durable queue
    await _enqueue(app.state.ch, sid, start_job(sid) if repo else chat_job(sid))
    return {"id": sid, "status": "queued", "title": row.title, "repo": row.repo}


@app.get("/sessions")
def sessions(user: User = Depends(auth.current_user)):
    """The user's chats for the sidebar, most recently active first."""
    return [_summary(r) for r in list_sessions(user.id)]


@app.get("/sessions/{sid}")
async def session(sid: str, user: User = Depends(auth.current_user)):
    row = _row(sid, user)
    return {**_summary(row), "task": row.task, "repo_url": row.repo_url, "work_branch": row.work_branch,
            "created_at": as_utc(row.created_at), "sandbox_status": await _status(sid) if row.repo else None}


@app.patch("/sessions/{sid}")
def rename(sid: str, body: Rename, user: User = Depends(auth.current_user)):
    _row(sid, user)
    set_title(sid, body.title)
    return _summary(get_session(sid))


@app.get("/sessions/{sid}/events")
def events(sid: str, after_seq: int = Query(0, ge=0), user: User = Depends(auth.current_user)):
    _row(sid, user)
    return [{"seq": e.seq, "ts": e.ts, "type": e.type, "payload": e.payload}
            for e in load_events(sid, after_seq=after_seq)]


def _event_json(e) -> dict:
    return {"seq": e.seq, "ts": e.ts.isoformat(), "type": e.type, "payload": e.payload}


async def _send_after(websocket, sid, last) -> int:
    """Send every stored event with seq > last, in order. Returns the last seq sent."""
    for e in await asyncio.to_thread(load_events, sid, last):
        await websocket.send_text(json.dumps(_event_json(e)))
        last = e.seq
    return last


async def _stream(websocket, sid, after_seq, q):
    """Replay events after after_seq, then send new ones as notifications arrive on q."""
    last = await _send_after(websocket, sid, after_seq)
    loop = asyncio.get_running_loop()
    next_ping = loop.time() + PING_INTERVAL
    while True:
        try:
            seq = await asyncio.wait_for(q.get(), max(next_ping - loop.time(), 0))
        except TimeoutError:
            await websocket.send_text(json.dumps({"type": "ping"}))
            next_ping = loop.time() + PING_INTERVAL
            continue
        # seqs up to `last` were sent already (dedupe). Reading everything after `last` also fills
        # gaps: notified of 5 when 4 never was sends 4, then 5. None: notifications may be lost
        if seq is None or seq > last:
            last = await _send_after(websocket, sid, last)


async def _read_until_closed(websocket):
    """The socket is read-only: drop whatever the client sends, and return once it disconnects."""
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass


@app.post("/sessions/{sid}/ws-ticket")
def ws_ticket(sid: str, user: User = Depends(auth.current_user)):
    """A single-use ticket, good for TICKET_TTL seconds, to open this session's WebSocket."""
    _row(sid, user)
    return {"ticket": tokens.issue_ticket(user.id, sid)}


@app.websocket("/sessions/{sid}/ws")
async def watch(websocket: WebSocket, sid: str, ticket: str | None = None, after_seq: int = Query(0, ge=0)):
    """Events with seq > after_seq, then new ones live, as JSON {seq, ts, type, payload}.

    A {"type": "ping"} goes out every PING_INTERVAL seconds. To resume after a drop, get a new
    ticket and reconnect with after_seq=<last seq received>. Follow-ups go through
    POST /sessions/{sid}/messages.

    Needs a ticket from POST /sessions/{sid}/ws-ticket (browsers can't send an Authorization
    header on a WebSocket, and access tokens don't belong in URLs) and an Origin in CORS_ORIGINS.
    Refusals close with 4403 (origin), 4401 (no valid ticket) or 4404 (no such session).
    """
    await websocket.accept()  # then close, so the client sees the code (a refused handshake is a bare 403)
    if websocket.headers.get("origin") not in config.CORS_ORIGINS:
        await websocket.close(code=4403, reason="origin not allowed")
        return
    user_id = tokens.take_ticket(ticket, sid)
    if user_id is None:
        await websocket.close(code=4401, reason="get a ticket from POST /sessions/{id}/ws-ticket")
        return
    row = await asyncio.to_thread(get_session, sid)
    if row is None or row.user_id != user_id:
        await websocket.close(code=4404, reason=f"no session {sid!r}")
        return
    q = live.subscribe(sid)  # before the replay, so nothing committed in between is missed
    try:
        async with anyio.create_task_group() as tg:
            async def read():
                await _read_until_closed(websocket)
                tg.cancel_scope.cancel()  # the client went away: stop streaming

            tg.start_soon(read)
            await _stream(websocket, sid, after_seq, q)  # only ends on an error
    except* WebSocketDisconnect:
        pass
    except* Exception as eg:
        e = eg.exceptions[0]
        print(f"[gateway] event stream for {sid} failed: {type(e).__name__}: {e}", flush=True)
        with suppress(Exception):
            await websocket.close(code=1011)
    finally:
        live.unsubscribe(sid, q)


@app.post("/sessions/{sid}/messages", status_code=202)
async def follow_up(sid: str, body: FollowUp, user: User = Depends(auth.current_user)):
    """The next message. A repo given to a plain chat attaches it: the chat gets a sandbox and
    the agent takes over. A chat keeps its first repo: another one is 409."""
    ch = app.state.ch
    row = _row(sid, user)
    _within_limit(user)
    if body.repo and row.repo and body.repo.lower() != row.repo.lower():
        raise HTTPException(409, NEW_REPO)
    repo = await _repo_for(user, row.repo or body.repo) if row.repo or body.repo else None
    async with app.state.create_lock:  # count + claim as one step within this gateway
        if repo and row.status in IDLE:
            _room_for_an_agent(user)
        # claim the session atomically; a busy one (or a concurrent follow-up) gets 409
        if not transition(sid, "provisioning", IDLE):
            raise HTTPException(409, f"session {sid} is {_row(sid, user).status}; wait until it finishes")
    if repo is None:
        await _enqueue(ch, sid, chat_job(sid, body.text))
        return {"id": sid, "status": "queued", "repo": None}
    attaching = row.repo is None
    if attaching and not attach_repo(sid, repo["full_name"]):
        # another follow-up attached a repo between our read and our claim
        if get_session(sid).repo.lower() != repo["full_name"].lower():
            transition(sid, row.status, {"provisioning"})
            raise HTTPException(409, NEW_REPO)
    try:
        if attaching:
            await _create_sandbox(sid, repo)
        else:
            await _wake_sandbox(ch, sid, repo)
    except HTTPException:
        raise
    except Exception as e:
        _fail(sid, "sandbox", e)
    await _enqueue(ch, sid, resume_job(sid, body.text))
    return {"id": sid, "status": "queued", "repo": repo["full_name"]}


async def _wake_sandbox(ch, sid, repo):
    """Reuse the session's sandbox if its runner answers; otherwise start a new one."""
    state = await asyncio.to_thread(sandbox.sandbox_status, sid)
    warm = state == "running" and (await _control(ch, sid, "control.ping")).get("pong") is True
    if warm:
        append_event(sid, "sandbox.reused", {})
        return
    # clear the old Job (its name is reused) before the queues, so nothing requeues stale work
    await asyncio.to_thread(sandbox.remove_sandbox, sid)
    for q in await _queues(ch, sid):
        await q.purge()
    # the entrypoint checks out otto/<sid>, so pushed work carries over
    await _create_sandbox(sid, repo)
    append_event(sid, "sandbox.recreated", {"previous": state})


@app.post("/sessions/{sid}/stop")
async def stop(sid: str, user: User = Depends(auth.current_user)):
    """Stop the session and its sandbox; it stays in the list, and a follow-up starts it again."""
    row = _row(sid, user)
    # stopped first: a worker still running this session ends after its current step
    set_status(sid, "stopped")
    if row.repo:  # a plain chat has no sandbox
        await _destroy_sandbox(app.state.ch, sid)
    return {"id": sid, "status": "stopped"}


@app.delete("/sessions/{sid}")
async def delete_chat(sid: str, user: User = Depends(auth.current_user)):
    """Delete the chat: stop its sandbox (and its queues), then delete its events and the session.
    Its token usage stays on the user's account."""
    row = _row(sid, user)
    if row.status in ACTIVE:
        set_status(sid, "stopped")  # a worker on it ends after its current step
    if row.repo:  # a plain chat has no sandbox or queues
        await _destroy_sandbox(app.state.ch, sid)
    await asyncio.to_thread(delete_session, sid)
    return {"id": sid, "deleted": True}


@app.post("/sessions/{sid}/sandbox/stop")
async def stop_sandbox(sid: str, user: User = Depends(auth.current_user)):
    """Stop just the sandbox. A session between turns keeps its status (a follow-up starts a new
    sandbox); one that is working can't go on without it, so it is stopped too."""
    row = _row(sid, user)
    if row.status in ACTIVE:
        set_status(sid, "stopped")
    if row.repo:
        await _destroy_sandbox(app.state.ch, sid)
    return {"id": sid, "status": get_session(sid).status, "sandbox_status": "missing"}


@app.delete("/me")
async def delete_me(response: Response, user: User = Depends(auth.current_user)):
    """Delete the account: stop the user's sessions and sandboxes, then delete everything of theirs."""
    for row in await asyncio.to_thread(list_sessions, user.id):
        if row.status in ACTIVE:
            set_status(row.id, "stopped")  # a worker on it ends after its current step
        if row.repo:
            try:
                await _destroy_sandbox(app.state.ch, row.id)
            except Exception as e:  # best effort: a sandbox ends by itself within SANDBOX_MAX_AGE_SECONDS
                print(f"[gateway] deleting user {user.id}: sandbox of {row.id}: {e}", flush=True)
    await asyncio.to_thread(delete_account, user.id)
    github_app.forget(user.id)
    auth.clear_login(response)
    auth.clear_refresh(response)
    return {"ok": True}


@app.get("/usage")
async def usage_summary(user: User = Depends(auth.current_user)):
    """Tokens today (against the daily limit), this month, per day and per model; live sandboxes."""
    out = await asyncio.to_thread(usage.summary, user.id)
    # a sandbox lives at most SANDBOX_MAX_AGE_SECONDS, and creating one updates its session
    since = utcnow() - timedelta(seconds=config.SANDBOX_MAX_AGE_SECONDS + 60)
    live = []
    for row in await asyncio.to_thread(repo_sessions_since, user.id, since):
        if (state := await _status(row.id)) == "running":
            live.append({"session_id": row.id, "title": row.title, "repo": row.repo, "sandbox_status": state})
    return {**out, "active_sandboxes": live}


async def _destroy_sandbox(ch, sid):
    """Shut the session's runner down (best effort), delete its Job and its queues."""
    if await _status(sid) == "running":
        try:
            await _control(ch, sid, "control.shutdown")  # best effort
        except Exception as e:
            print(f"[gateway] shutdown of {sid} failed: {e}", flush=True)
    try:
        await asyncio.to_thread(sandbox.destroy_sandbox, sid)
    except ApiException as e:
        if e.status != 404:  # no Job is fine
            append_event(sid, "error", {"stage": "destroy_sandbox", "message": redact(str(e))[:2000]})
            raise HTTPException(502, f"destroy_sandbox failed: {redact(str(e))[:500]}")
    except Exception as e:
        append_event(sid, "error", {"stage": "destroy_sandbox", "message": redact(str(e))[:2000]})
        raise HTTPException(502, f"destroy_sandbox failed: {redact(str(e))[:500]}")
    for q in await _queues(ch, sid):
        await q.delete(if_unused=False, if_empty=False)
