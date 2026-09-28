import json

from brain.resume import INTERRUPTED, rebuild_messages
from shared.models import SessionEvent

SYS = {"role": "system", "content": "sys"}
USER = {"role": "user", "content": "fix it"}


def events(*items):
    """items: message dicts (-> llm.message) or (type, payload) pairs."""
    out = []
    for seq, it in enumerate(items, 1):
        type, payload = it if isinstance(it, tuple) else ("llm.message", {"message": it})
        out.append(SessionEvent(session_id="s1", seq=seq, type=type, payload=payload))
    return out


def assistant(*ids, content=None):
    return {"role": "assistant", "content": content, "tool_calls": [
        {"id": i, "type": "function", "function": {"name": "git_status", "arguments": "{}"}}
        for i in ids]}


def tool(i, content="{}"):
    return {"role": "tool", "tool_call_id": i, "content": content}


def synthetic(i):
    return {"role": "tool", "tool_call_id": i, "content": json.dumps(INTERRUPTED)}


def test_replays_only_llm_messages_in_order():
    evs = events(("session.created", {"task": "fix it"}), SYS, USER,
                 ("session.status", {"status": "running"}), assistant("c0"),
                 ("bus.action", {"action_id": "a"}), tool("c0", "out"),
                 {"role": "assistant", "content": "done"})
    assert rebuild_messages(evs) == [SYS, USER, assistant("c0"), tool("c0", "out"),
                                     {"role": "assistant", "content": "done"}]


def test_crash_mid_turn_gets_synthetic_results():
    evs = events(SYS, USER, assistant("c0", "c1", "c2"), tool("c1", "got c1"))
    assert rebuild_messages(evs) == [SYS, USER, assistant("c0", "c1", "c2"),
                                     tool("c1", "got c1"), synthetic("c0"), synthetic("c2")]
    assert INTERRUPTED == {"exit_code": 1, "stdout": "",
                           "stderr": "interrupted: result lost when the session stopped; re-run if needed"}


def test_missing_results_before_a_later_message_are_filled_in_place():
    evs = events(SYS, USER, assistant("c0"), {"role": "user", "content": "go on"})
    assert rebuild_messages(evs) == [SYS, USER, assistant("c0"), synthetic("c0"),
                                     {"role": "user", "content": "go on"}]


def test_orphan_and_duplicate_tool_results_are_dropped():
    evs = events(SYS, USER, tool("stray"), assistant("c0"), tool("c0", "first"), tool("c0", "again"))
    assert rebuild_messages(evs) == [SYS, USER, assistant("c0"), tool("c0", "first")]


def test_no_events():
    assert rebuild_messages([]) == []
