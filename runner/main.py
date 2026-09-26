import asyncio, json, traceback
from aio_pika import message, connect_robust

from shared import config
from shared.bus import actions_queue, results_queue, make_result
from runner.handlers import REGISTRY


async def main():
    bus = config.BUS_URL
    sid = config.SESSION_ID

    conn = await connect_robust(bus)
    ch = await conn.channel()
    await ch.set_qos(prefetch_count=1)


    actions = await ch.declare_queue(actions_queue(sid), durable=True)
    await ch.declare_queue(results_queue(sid), durable=True)
    print(f"[runner] Listening for actions on {actions_queue(sid)}", flush=True)

    async with actions.iterator() as it:
        async for msg in it:
            async with msg.process():
                action = json.loads(msg.body)
                kind = action.get("kind", "")
                print(f"[runner] {kind} {action.get('action_id')}", flush=True)

                fn = REGISTRY.get(kind)

                try:
                    if not fn:
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


if __name__ == "__main__":
    asyncio.run(main())
