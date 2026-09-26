import sys, asyncio
from aio_pika import connect

from shared import config
from shared.bus import actions_queue, results_queue
from brain.loop import run_session

USAGE = 'usage: python -m brain.main "task text"'


async def main(task):
    sid = config.SESSION_ID
    conn = await connect(config.BUS_URL)
    ch = await conn.channel()
    await ch.declare_queue(actions_queue(sid), durable=True)
    results = await ch.declare_queue(results_queue(sid), durable=True)
    await run_session(ch, results, sid, task)
    await conn.close()

if __name__== "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(USAGE)
        sys.exit(0 if len(sys.argv) > 1 else 2)
    asyncio.run(main(" ".join(sys.argv[1:])))
