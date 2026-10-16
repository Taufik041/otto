import asyncio
import json
import sys

from aio_pika import DeliveryMode, Message, connect

from shared import config
from shared.bus import actions_queue, make_action, results_queue


async def main():
    connection = await connect(config.BUS_URL)
    sid = config.SESSION_ID

    async with connection:
        channel = await connection.channel()
        kind = sys.argv[1]
        payload = json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
        action = make_action(sid, kind, payload)
        message= Message(
            json.dumps(action).encode(),
            delivery_mode=DeliveryMode.PERSISTENT
        )
        await channel.declare_queue(actions_queue(sid), durable=True)
        results = await channel.declare_queue(results_queue(sid), durable=True)

        await channel.default_exchange.publish(
                    message,
                    routing_key=actions_queue(sid),
                )
        print(f"[poke] sent {action['action_id']}", flush=True)

        async with results.iterator() as it:
            async for msg in it:
                async with msg.process():
                    try:
                        result = json.loads(msg.body)
                    except json.JSONDecodeError:
                        print("[poke] dropped non-JSON message", flush=True)
                        continue

                    if result.get("action_id") == action["action_id"]:
                        print(f"[poke] got result: {result}", flush=True)
                        return
if __name__== "__main__":
    asyncio.run(main())
