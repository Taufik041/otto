"""Whether the workers (the sandbox cluster) are reachable, checked at most every
WORKERS_CHECK_SECONDS. Offline, plain chats still work; agent work is refused up front with
503 {"error": "workers_offline"}, before anything is created."""
import asyncio, threading, time

from gateway.errors import Refused
from orchestrator import sandbox
from shared import config

OFFLINE = "Otto's workers are offline right now. Plain chat still works."

_checked: tuple[float, bool] | None = None  # (monotonic time, online)
_lock = threading.Lock()


def online_now() -> bool:
    """The cached answer while it's fresh, else a new check (sandbox.reachable, which never raises)."""
    global _checked
    with _lock:  # one check at a time; the others wait and use its answer
        if _checked and time.monotonic() - _checked[0] < config.WORKERS_CHECK_SECONDS:
            return _checked[1]
        ok = sandbox.reachable()
        _checked = (time.monotonic(), ok)
        return ok


async def online() -> bool:
    return await asyncio.to_thread(online_now)


async def require():
    """Refused 503 workers_offline unless the workers are reachable."""
    if not await online():
        raise Refused(503, "workers_offline", OFFLINE)


def forget():
    """Check again next time (e.g. a sandbox couldn't be created after all)."""
    global _checked
    with _lock:
        _checked = None
