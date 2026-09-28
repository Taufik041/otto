import asyncio, json
from aio_pika import Message

from shared.bus import actions_queue, make_action

BUS_TIMEOUT = 120  # seconds to wait for a runner result


def start_consumer(results):
    """Start the session's single results consumer.

    Returns (pending, task): pending maps action_id -> Future, resolved by the
    consumer when the matching result arrives. Pass pending to bus_call.
    """
    pending = {}
    task = asyncio.create_task(_consume(results, pending))
    return pending, task


async def stop_consumer(pending, task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    for fut in pending.values():
        fut.cancel()
    pending.clear()


async def _consume(results, pending):
    async with results.iterator() as it:
        async for msg in it:
            async with msg.process():
                try:
                    r = json.loads(msg.body)
                except ValueError:
                    print(f"[bus] dropped non-JSON result: {msg.body[:200]!r}", flush=True)
                    continue
                aid = r.get("action_id") if isinstance(r, dict) else None
                fut = pending.pop(aid, None)
                if fut is None or fut.done():
                    print(f"[bus] dropped result for unknown action {aid}", flush=True)
                    continue
                fut.set_result(r)


async def bus_call(ch, pending, sid, kind, payload, timeout=BUS_TIMEOUT, record=None) -> dict:
    """Send one action and wait for its result payload.

    record(type, payload), if given, is called with bus.action before publishing
    and bus.result once the result (or a timeout) is in.
    """
    action = make_action(sid, kind, payload)
    aid = action["action_id"]
    if record:
        record("bus.action", {"action_id": aid, "kind": kind, "payload": payload})
    fut = asyncio.get_running_loop().create_future()
    pending[aid] = fut  # register before publishing so a fast result isn't missed
    try:
        await ch.default_exchange.publish(
            Message(json.dumps(action).encode()),
            routing_key=actions_queue(sid)
        )
        r = await asyncio.wait_for(fut, timeout)
        ok, result = r.get("ok"), r.get("payload", {})
    except TimeoutError:
        ok, result = False, {"exit_code": 1, "stdout": "",
                             "stderr": f"timed out after {timeout}s waiting for the result of {kind} (action {aid})"}
    finally:
        pending.pop(aid, None)
    if record:
        record("bus.result", {"action_id": aid, "ok": ok, "payload": result})
    return result
