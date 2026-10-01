import uuid


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
