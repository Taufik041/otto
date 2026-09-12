import asyncio
import json
import os
import traceback

from aio_pika import Message, connect_robust

from handlers import handle_execution

async def main():
    bus_url = os.environ.get("BUS_URL", "amqp://guest:guest@localhost/")
    sid = os.environ.get("SESSION_ID", "s1")

    connection = await connect_robust(bus_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)

    actions = await channel.declare_queue(f"actions.{sid}", durable=True)
    await channel.declare_queue(f"results.{sid}", durable=True)
    print(f"[runner] ready, session={sid}", flush=True)

    async with actions.iterator() as queue_iter:
        async for msg in queue_iter:
            async with msg.process():  # acks when block exits cleanly
                try:
                    action = json.loads(msg.body)
                except json.JSONDecodeError:
                    print("[runner] dropped non-JSON message", flush=True)
                    continue

                kind = action.get("kind", "")
                print(f"[runner] action {action.get('action_id')} kind={kind}", flush=True)

                try:
                    if kind.startswith("shell."):
                        payload = handle(action.get("payload", {}))
                        ok = payload.get("exit_code", -1) != -1
                    else:
                        payload = {"error": f"unknown kind: {kind}"}
                        ok = False
                except Exception:
                    payload = {"error": traceback.format_exc()}
                    ok = False

                result = {
                    "session_id": sid,
                    "action_id": action.get("action_id"),
                    "kind": f"{kind}.result",
                    "ok": ok,
                    "payload": payload,
                }
                await channel.default_exchange.publish(
                    Message(json.dumps(result).encode()),
                    routing_key=f"results.{sid}",
                )

if __name__ == "__main__":
    asyncio.run(main())