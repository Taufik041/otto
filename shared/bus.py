import asyncio, uuid

RECONNECT_MAX = 30  # seconds between first-connect attempts, at most


def actions_queue(sid: str) -> str:
    return f"otto.{sid}.actions"


def results_queue(sid: str) -> str:
    return f"otto.{sid}.results"


def make_action(sid: str, kind: str, payload: dict) -> dict:
    return {
        "session_id": sid,
        "action_id": str(uuid.uuid4()),
        "kind": kind,
        "payload": payload
    }


def make_result(action: dict, ok: bool, payload: dict) -> dict:
    return {
        "session_id": action.get("session_id"),
        "action_id": action.get("action_id"),
        "kind": f"{action.get('kind', '')}.result",
        "ok": ok,
        "payload": payload
    }


SESSIONS_QUEUE = "otto.sessions"  # gateway -> brain workers: which session to run next


def start_job(sid: str) -> dict:
    return {"type": "start", "session_id": sid}


def resume_job(sid: str, text: str) -> dict:
    return {"type": "resume", "session_id": sid, "text": text}


def chat_job(sid: str, text: str | None = None) -> dict:
    """A plain-chat turn: the first message (no text) or a follow-up."""
    return {"type": "chat", "session_id": sid, **({"text": text} if text is not None else {})}


def retry_job(sid: str) -> dict:
    """Run a failed turn again from where it stopped, with no new message."""
    return {"type": "retry", "session_id": sid}


async def connect_with_backoff(connect, url, name, max_delay=RECONNECT_MAX, sleep=asyncio.sleep):
    """connect(url) (aio_pika's connect_robust), retried with exponential backoff until the broker
    answers: connect_robust reconnects by itself, but only after a first successful connect. The
    URL is never printed (it holds the password)."""
    delay = 1
    while True:
        try:
            return await connect(url)
        except Exception as e:
            print(f"[{name}] bus connect failed ({type(e).__name__}); retrying in {delay}s", flush=True)
            await sleep(delay)
            delay = min(delay * 2, max_delay)
