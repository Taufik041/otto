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
