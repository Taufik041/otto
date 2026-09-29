"""Otto's HTTP API: create sessions, follow up, watch events, stop them.

    uvicorn gateway.app:app --port 8000

The gateway owns sandboxes (via the orchestrator) and the session queues (via
the bus); brain workers run the sessions it enqueues on otto.sessions.
"""
import asyncio, json, uuid
from contextlib import asynccontextmanager

from aio_pika import DeliveryMode, Message, connect_robust
from fastapi import FastAPI, HTTPException, Query
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


class NewSession(BaseModel):
    repo_url: str
    task: str = Field(min_length=1)

    @field_validator("repo_url")
    @classmethod
    def github_repo(cls, v):
        parse_repo(v)  # ValueError -> 422
        return v.strip()


class FollowUp(BaseModel):
    text: str = Field(min_length=1)


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
            "pr_url": row.pr_url, "created_at": row.created_at}


@app.post("/sessions", status_code=201)
async def create(body: NewSession):
    async with app.state.create_lock:  # count + insert as one step within this gateway
        if count_active() >= config.MAX_ACTIVE_SESSIONS:
            raise HTTPException(429, f"{config.MAX_ACTIVE_SESSIONS} sessions are already active; try again later")
        sid = new_session_id()
        create_session(sid, task=body.task, repo_url=body.repo_url, model=config.MODEL, status="provisioning")
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
