import asyncio, json, sys, traceback

from aio_pika import connect_robust

from shared import config
from shared.bus import SESSIONS_QUEUE, actions_queue, connect_with_backoff, results_queue
from shared.sessions import get_session, transition
from brain.loop import chat_session, has_conversation, resume_session, retry_chat, start_session
from brain.main import connect_db


def parse_job(body) -> dict | None:
    """{"type": "start"|"resume"|"chat"|"retry", "session_id": ..., "text": ... (resume; chat
    follow-ups)}, or None if malformed."""
    try:
        job = json.loads(body)
    except ValueError:
        return None
    if not isinstance(job, dict) or not isinstance(job.get("session_id"), str):
        return None
    kind, text = job.get("type"), job.get("text")
    if kind in ("start", "retry") or (kind == "resume" and isinstance(text, str)) \
            or (kind == "chat" and (text is None or isinstance(text, str))):
        return job
    return None


async def run_job(conn, job):
    """Run one session turn on its own channel, with the same loop functions as the CLI."""
    sid = job["session_id"]
    row = get_session(sid)
    if job["type"] == "chat" or (job["type"] == "retry" and row is not None and row.repo is None):
        # a plain chat: no sandbox, so no bus
        if job["type"] == "chat":
            await chat_session(sid, job.get("text"))
        else:
            await retry_chat(sid)
        return
    ch = await conn.channel()
    try:
        await ch.declare_queue(actions_queue(sid), durable=True)
        results = await ch.declare_queue(results_queue(sid), durable=True)
        if job["type"] == "start" or (job["type"] == "retry" and not has_conversation(sid)):
            await start_session(ch, results, sid, get_session(sid).task)
        else:  # resume with the new message, or retry (None) from where the turn stopped
            await resume_session(ch, results, sid, job.get("text"))
    finally:
        # the runner and its queues stay: the sandbox is kept warm for follow-ups
        await ch.close()


async def handle(conn, msg, slots):
    try:
        job = parse_job(msg.body)
        if job is None:
            await msg.ack()
            print(f"[worker] dropped malformed job: {msg.body[:200]!r}", flush=True)
            return
        sid = job["session_id"]
        # ack as the session starts: the DB is the record of truth (the gateway's crash sweep
        # catches dead workers), and long sessions don't run into RabbitMQ's consumer timeout
        started = transition(sid, "running", {"queued"})
        await msg.ack()
        if not started:
            row = get_session(sid)
            print(f"[worker] skipped {job['type']} for session {sid}: "
                  f"{'no such session' if row is None else 'status is ' + row.status}", flush=True)
            return
        print(f"[worker] {job['type']} session {sid}", flush=True)
        try:
            await run_job(conn, job)
        except asyncio.CancelledError:
            raise
        except Exception:
            if get_session(sid) is None:  # deleted mid-turn: its events had nowhere to go
                print(f"[worker] session {sid} was deleted", flush=True)
                return
            traceback.print_exc()
            transition(sid, "failed", {"running"})  # the loop has usually done this already
        row = get_session(sid)
        print(f"[worker] session {sid} {'was deleted' if row is None else 'is ' + row.status}", flush=True)
    finally:
        slots.release()


async def consume(conn, queue, concurrency):
    """Run up to `concurrency` sessions at once, each as its own task, until the queue closes."""
    slots = asyncio.Semaphore(concurrency)
    tasks = set()
    try:
        async with queue.iterator() as it:
            async for msg in it:
                await slots.acquire()
                task = asyncio.create_task(handle(conn, msg, slots))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()  # run_loop marks each session interrupted
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    connect_db()
    conn = await connect_with_backoff(connect_robust, config.BUS_URL, "worker")
    try:
        ch = await conn.channel()
        await ch.set_qos(prefetch_count=config.WORKER_CONCURRENCY)
        queue = await ch.declare_queue(SESSIONS_QUEUE, durable=True)
        print(f"[worker] consuming {SESSIONS_QUEUE}, up to {config.WORKER_CONCURRENCY} sessions at once",
              flush=True)
        await consume(conn, queue, config.WORKER_CONCURRENCY)
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit("[worker] interrupted")
