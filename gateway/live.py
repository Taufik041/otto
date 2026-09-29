"""Live event notifications for the gateway's WebSockets.

One LISTEN connection per gateway process receives the NOTIFY that append_event
sends for each stored event ("<session_id>:<seq>") and hands the seq to every
in-process subscriber of that session. Subscribers read the rows themselves.

A subscriber's queue carries seqs, or None for "notifications may have been
missed" (after a reconnect): re-read everything newer than what you have.
"""
import asyncio
from contextlib import suppress

import psycopg
from sqlalchemy.engine import make_url

from shared.events import CHANNEL

RECONNECT_MAX = 30   # seconds between reconnect attempts, at most
HEALTH_CHECK = 30    # seconds without notifications before checking the connection is alive

_subscribers: dict[str, set[asyncio.Queue]] = {}  # session_id -> queues


def subscribe(sid) -> asyncio.Queue:
    q = asyncio.Queue()
    _subscribers.setdefault(sid, set()).add(q)
    return q


def unsubscribe(sid, q):
    queues = _subscribers.get(sid)
    if queues is None:
        return
    queues.discard(q)
    if not queues:
        del _subscribers[sid]


def publish(sid, seq):
    for q in _subscribers.get(sid, ()):
        q.put_nowait(seq)


def resync():
    for queues in _subscribers.values():
        for q in queues:
            q.put_nowait(None)


def dispatch(payload):
    """Handle one NOTIFY payload, "<session_id>:<seq>"."""
    sid, _, seq = payload.rpartition(":")
    try:
        seq = int(seq)
    except ValueError:
        sid = ""
    if not sid:
        print(f"[live] ignored notification {payload[:200]!r}", flush=True)
        return
    publish(sid, seq)


def pg_url(url) -> str:
    """A libpq URL from a SQLAlchemy one (postgresql+psycopg://... -> postgresql://...)."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


async def _connect(url):
    return await psycopg.AsyncConnection.connect(url, autocommit=True)


async def listen(url, connect=_connect):
    """LISTEN and dispatch notifications until cancelled, reconnecting with backoff."""
    delay = 1
    while True:
        try:
            async with await connect(url) as conn:
                await conn.execute(f"LISTEN {CHANNEL}")
                print(f"[live] listening on {CHANNEL}", flush=True)
                delay = 1
                resync()  # anything committed while we weren't listening
                while True:
                    async for n in conn.notifies(timeout=HEALTH_CHECK):
                        dispatch(n.payload)
                    # quiet for a while: a dead connection would stay quiet forever, so probe it
                    await conn.execute("SELECT 1")
        except Exception as e:
            print(f"[live] listener connection failed ({type(e).__name__}: {e}); "
                  f"reconnecting in {delay}s", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX)


def start(url, connect=_connect) -> asyncio.Task:
    return asyncio.create_task(listen(url, connect))


async def stop(task):
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
