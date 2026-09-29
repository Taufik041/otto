"""Otto's HTTP API: list models, create sessions, follow up, watch events (also live, over a WebSocket), stop them.

    uvicorn gateway.app:app --port 8000

The gateway owns sandboxes (via the orchestrator) and the session queues (via
the bus); brain workers run the sessions it enqueues on otto.sessions.
"""
import asyncio, json, uuid
from contextlib import asynccontextmanager, suppress

import anyio
from aio_pika import DeliveryMode, Message, connect_robust
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketDisconnect
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel, Field, field_validator

from brain.bus import bus_call, start_consumer, stop_consumer
from gateway import live
from orchestrator import sandbox
from shared import config
from shared.bus import SESSIONS_QUEUE, actions_queue, resume_job, results_queue, start_job
from shared.db import get_engine, init_db
from shared.events import append_event, load_events, redact
from shared.github import parse_repo
from shared.sessions import (ACTIVE, count_active, create_session, get_session, list_sessions,
                             set_status, sweep_stale_sessions, transition)

PING_TIMEOUT = 5  # seconds to wait for a warm runner to answer control.ping / control.shutdown
PING_INTERVAL = 20  # seconds between WebSocket heartbeats
IDLE = ("pending", "done", "failed", "interrupted", "stopped")  # statuses that may take a follow-up


@asynccontextmanager
async def lifespan(app):
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
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])


class NewSession(BaseModel):
    repo_url: str
    task: str = Field(min_length=1)
    model: str | None = None  # a catalog id (GET /models); None: the default model

    @field_validator("repo_url")
    @classmethod
    def github_repo(cls, v):
        parse_repo(v)  # ValueError -> 422
        return v.strip()

    @field_validator("model")
    @classmethod
    def available_model(cls, v):
        if v is not None and not config.is_available(v):
            raise ValueError(f"unknown or unavailable model {v!r}; see GET /models")
        return v


class FollowUp(BaseModel):
    text: str = Field(min_length=1)
    model: str | None = None  # only to refuse it: a session stays on the model it was created with

    @field_validator("model")
    @classmethod
    def no_switching(cls, v):
        if v is not None:
            raise ValueError("a session's model is fixed at creation; start a new session for another model")
        return v


def new_session_id() -> str:
    return uuid.uuid4().hex[:10]  # lowercase alphanumerics: a valid k8s name


def _row(sid):
    row = get_session(sid)
    if row is None:
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
    return {"id": row.id, "repo_url": row.repo_url, "task": row.task, "status": row.status,
            "model": row.model, "pr_url": row.pr_url, "created_at": row.created_at}


@app.get("/models")
def models():
    """The model catalog for the frontend's picker; available: its provider has an API key."""
    return {"default_model": config.DEFAULT_MODEL,
            "models": [{"id": m["id"], "label": m["label"], "provider": m["provider"],
                        "available": config.is_available(m["id"])} for m in config.MODELS]}


@app.post("/sessions", status_code=201)
async def create(body: NewSession):
    model = body.model or config.DEFAULT_MODEL
    if not config.is_available(model):
        raise HTTPException(503, f"default model {model!r} is not available: set OPENROUTER_API_KEY, "
                                 "or OPENAI_API_KEY with OTTO_OPENAI_MODELS (see GET /models)")
    async with app.state.create_lock:  # count + insert as one step within this gateway
        if count_active() >= config.MAX_ACTIVE_SESSIONS:
            raise HTTPException(429, f"{config.MAX_ACTIVE_SESSIONS} sessions are already active; try again later")
        sid = new_session_id()
        create_session(sid, task=body.task, repo_url=body.repo_url, model=model, status="provisioning")
    try:
        await asyncio.to_thread(sandbox.create_sandbox, sid, body.repo_url)
    except Exception as e:
        _fail(sid, "create_sandbox", e)
    # the runner needn't be up yet: its actions wait in the durable queue
    await _enqueue(app.state.ch, sid, start_job(sid))
    return {"id": sid, "status": "queued"}


@app.get("/sessions")
def sessions():
    return [_summary(r) for r in list_sessions()]


@app.get("/sessions/{sid}")
async def session(sid: str):
    row = _row(sid)
    return {**_summary(row), "model": row.model, "work_branch": row.work_branch,
            "updated_at": row.updated_at, "sandbox_status": await _status(sid)}


@app.get("/sessions/{sid}/events")
def events(sid: str, after_seq: int = Query(0, ge=0)):
    _row(sid)
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


@app.websocket("/sessions/{sid}/ws")
async def watch(websocket: WebSocket, sid: str, after_seq: int = Query(0, ge=0)):
    """Events with seq > after_seq, then new ones live, as JSON {seq, ts, type, payload}.

    A {"type": "ping"} goes out every PING_INTERVAL seconds. To resume after a drop, reconnect
    with after_seq=<last seq received>. Follow-ups go through POST /sessions/{sid}/messages.
    """
    await websocket.accept()  # then close, so the client sees the 4404 (a refused handshake is a bare 403)
    if get_session(sid) is None:
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
async def follow_up(sid: str, body: FollowUp):
    ch = app.state.ch
    _row(sid)
    # claim the session atomically; a busy one (or a concurrent follow-up) gets 409
    if not transition(sid, "provisioning", IDLE):
        raise HTTPException(409, f"session {sid} is {_row(sid).status}; wait until it finishes")
    try:
        state = await asyncio.to_thread(sandbox.sandbox_status, sid)
        warm = state == "running" and (await _control(ch, sid, "control.ping")).get("pong") is True
        if warm:
            append_event(sid, "sandbox.reused", {})
        else:
            # clear the old Job (its name is reused) before the queues, so nothing requeues stale work
            await asyncio.to_thread(sandbox.remove_sandbox, sid)
            for q in await _queues(ch, sid):
                await q.purge()
            # the entrypoint checks out otto/<sid>, so pushed work carries over
            await asyncio.to_thread(sandbox.create_sandbox, sid, _row(sid).repo_url)
            append_event(sid, "sandbox.recreated", {"previous": state})
    except HTTPException:
        raise
    except Exception as e:
        _fail(sid, "sandbox", e)
    await _enqueue(ch, sid, resume_job(sid, body.text))
    return {"id": sid, "status": "queued"}


@app.delete("/sessions/{sid}")
async def stop(sid: str):
    ch = app.state.ch
    _row(sid)
    # stopped first: a worker still running this session ends after its current step
    set_status(sid, "stopped")
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
    return {"id": sid, "status": "stopped"}
