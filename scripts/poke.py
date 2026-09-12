import asyncio
from aio_pika import Message, connect, DeliveryMode
import sys
import json, uuid, os



async def main():
    connection = await connect("amqp://guest:guest@localhost/")

    async with connection:
        channel = await connection.channel()
        kind = sys.argv[1]
        payload = json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
        action = {
            "session_id": "s1",
            "action_id": str(uuid.uuid4()),
            "kind": kind,
            "payload": payload
        }
        message= Message(
            json.dumps(action).encode(),
            delivery_mode=DeliveryMode.PERSISTENT
        )
        await channel.declare_queue("otto.s1.actions", durable=True)
        results = await channel.declare_queue("otto.s1.results", durable=True)

        await channel.default_exchange.publish(
                    message,
                    routing_key="otto.s1.actions",
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