import json
from aio_pika import Message

from shared.bus import actions_queue, make_action


async def bus_call(ch, results, sid, kind, payload) -> dict:
    action = make_action(sid, kind, payload)
    aid = action["action_id"]
    await ch.default_exchange.publish(
        Message(json.dumps(action).encode()),
        routing_key=actions_queue(sid)
    )
    async with results.iterator() as it:
        async for msg in it:
            async with msg.process():
                r = json.loads(msg.body)
                if r.get("action_id") == aid:
                    return r["payload"]

    return {}
