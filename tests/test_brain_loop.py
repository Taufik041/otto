import asyncio
import json

import pytest

from shared.bus import results_queue
from brain import loop
from tests.fakes import FakeChannel, auto_reply, llm_tool_calls, llm_final


def fake_client(monkeypatch, responses):
    """Patch brain.loop's OpenAI client; returns the list of create() kwargs."""
    calls = []

    class Completions:
        def create(self, **kw):
            calls.append(json.loads(json.dumps(kw["messages"], default=str)))
            return responses.pop(0)

    class Client:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(loop, "OpenAI", Client)
    return calls


@pytest.mark.asyncio
async def test_run_session_parallel_tool_calls(monkeypatch, capsys):
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    auto_reply(ch, results)
    calls = fake_client(monkeypatch, [
        llm_tool_calls(("git_status", {}), ("fs_read", {"path": "a.py"})),
        llm_final("done"),
    ])

    await asyncio.wait_for(loop.run_session(ch, results, "s1", "fix it"), 2)

    kinds = [a["kind"] for _, a in ch.default_exchange.published]
    assert kinds == ["git.status", "fs.read"]
    tool_msgs = [m for m in calls[1] if m["role"] == "tool"]
    assert [(m["tool_call_id"], json.loads(m["content"])["stdout"]) for m in tool_msgs] == [
        ("call_0", "ran git.status"), ("call_1", "ran fs.read")]
    assert "[otto] done" in capsys.readouterr().out
    # the result consumer is stopped when the session ends
    others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert others == []
