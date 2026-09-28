import asyncio, json, traceback
from aio_pika import message, connect_robust

from shared import config
from shared.bus import actions_queue, results_queue, make_result
from runner.handlers import REGISTRY

CONNECT_ATTEMPTS = 30
CONNECT_DELAY = 2  # seconds; ~60s in total


async def connect_with_retry(url):
    # connect_robust only reconnects after a first successful connect,
    # so retry the initial one while the broker comes up
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            return await connect_robust(url)
        except Exception as e:
            print(f"[runner] bus connect attempt {attempt}/{CONNECT_ATTEMPTS} failed: {e}", flush=True)
            if attempt < CONNECT_ATTEMPTS:
                await asyncio.sleep(CONNECT_DELAY)
    raise RuntimeError(f"could not connect to the bus after {CONNECT_ATTEMPTS} attempts "
                       f"({CONNECT_ATTEMPTS * CONNECT_DELAY}s); check BUS_URL and that RabbitMQ is up")


async def process(ch, sid, msg) -> bool:
    """Run one action and publish its result. Returns True when the runner should stop."""
    stop = False
    async with msg.process():
        try:
            action = json.loads(msg.body)  # ValueError covers bad JSON and bad UTF-8
        except ValueError:
            print(f"[runner] dropped non-JSON message: {msg.body[:200]!r}", flush=True)
            return False
        if not isinstance(action, dict):
            print(f"[runner] dropped message that is not a JSON object: {msg.body[:200]!r}", flush=True)
            return False

        kind = action.get("kind", "")
        print(f"[runner] {kind} {action.get('action_id')}", flush=True)

        fn = REGISTRY.get(kind)

        try:
            if kind == "control.ping":
                payload, ok = {"exit_code": 0, "pong": True}, True
            elif kind == "control.shutdown":
                payload, ok, stop = {"exit_code": 0, "stdout": "shutting down", "stderr": ""}, True, True
            elif not fn:
                payload, ok = {"exit_code": 1, "stdout": "", "stderr": f"Unknown action kind: {kind}"}, False
            else:
                payload = fn(action.get("payload", {}))
                ok = payload.get("exit_code", 1) == 0
        except Exception as e:
            payload, ok = {"exit_code": 1, "stdout": "", "stderr": f"Exception: {e}\n{traceback.format_exc()}"}, False

        result = make_result(action, ok, payload)

        await ch.default_exchange.publish(
            message.Message(body=json.dumps(result).encode()),
            routing_key=results_queue(sid)
        )
    return stop


async def serve(ch, actions, sid, idle_seconds) -> str:
    """Handle actions until control.shutdown, `idle_seconds` without any action, or the queue closes."""
    async with actions.iterator() as it:
        while True:
            try:
                # every action (control.ping included) restarts the idle clock
                msg = await asyncio.wait_for(it.__anext__(), idle_seconds)
            except StopAsyncIteration:
                return "closed"
            except TimeoutError:
                return "idle"
            if await process(ch, sid, msg):
                return "shutdown"


async def main():
    bus = config.BUS_URL
    sid = config.SESSION_ID
    idle = config.SANDBOX_IDLE_MINUTES * 60

    conn = await connect_with_retry(bus)
    try:
        ch = await conn.channel()
        await ch.set_qos(prefetch_count=1)

        actions = await ch.declare_queue(actions_queue(sid), durable=True)
        await ch.declare_queue(results_queue(sid), durable=True)
        print(f"[runner] Listening for actions on {actions_queue(sid)}", flush=True)

        reason = await serve(ch, actions, sid, idle)
    finally:
        await conn.close()
    if reason == "idle":
        print(f"[runner] idle: no actions for {config.SANDBOX_IDLE_MINUTES:g} min; exiting", flush=True)
    elif reason == "shutdown":
        print("[runner] shutdown requested; exiting", flush=True)


if __name__ == "__main__":
    asyncio.run(main())  # returns normally -> exit 0, so the Job completes and its ttl cleans it up
