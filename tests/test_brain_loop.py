import asyncio
import json

import pytest

from shared.bus import results_queue
from brain import loop
from tests.fakes import FakeChannel, auto_reply, llm_tool_calls, llm_final


def fake_client(monkeypatch, responses, delay=0):
    """Patch brain.loop's AsyncOpenAI client; returns the list of messages sent per call."""
    calls = []
    state = {"closed": False}

    class Completions:
        async def create(self, **kw):
            calls.append(json.loads(json.dumps(kw["messages"], default=str)))
            await asyncio.sleep(delay)
            return responses.pop(0)

    class Client:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": Completions()})()

        async def close(self):
            state["closed"] = True

    monkeypatch.setattr(loop, "AsyncOpenAI", Client)
    return calls, state


@pytest.mark.asyncio
async def test_run_session_parallel_tool_calls(monkeypatch, capsys):
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    auto_reply(ch, results)
    calls, state = fake_client(monkeypatch, [
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
    assert state["closed"]


@pytest.mark.asyncio
async def test_llm_call_does_not_block_the_event_loop(monkeypatch):
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    fake_client(monkeypatch, [llm_final("done")], delay=0.1)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    t = asyncio.ensure_future(ticker())
    await loop.run_session(ch, results, "s1", "hi")
    t.cancel()
    assert ticks >= 5
