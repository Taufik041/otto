import json

INTERRUPTED = {"exit_code": 1, "stdout": "",
               "stderr": "interrupted: result lost when the session stopped; re-run if needed"}


def rebuild_messages(events) -> list[dict]:
    """The chat `messages` list, replayed from a session's llm.message events.

    Repairs what the chat API would reject: every assistant tool call gets
    exactly one result right after it (a synthetic INTERRUPTED one if the
    session stopped before the real one was stored), and tool results that
    answer no open call are dropped.

    The latest system message is the one in force (a chat that gets a repo
    switches to the agent's prompt), and it goes first.
    """
    system = None
    out = []
    waiting = []  # tool_call ids of the last assistant message still without a result

    def fill_missing():
        for tc_id in waiting:
            out.append({"role": "tool", "tool_call_id": tc_id, "content": json.dumps(INTERRUPTED)})
        waiting.clear()

    for ev in events:
        if ev.type != "llm.message":
            continue
        m = ev.payload["message"]
        if m.get("role") == "system":
            system = m
            continue
        if m.get("role") == "tool":
            if m.get("tool_call_id") in waiting:
                waiting.remove(m["tool_call_id"])
                out.append(m)
            continue
        fill_missing()
        out.append(m)
        if m.get("role") == "assistant":
            waiting.extend(tc["id"] for tc in m.get("tool_calls") or [])
    fill_missing()
    return ([system] if system else []) + out
