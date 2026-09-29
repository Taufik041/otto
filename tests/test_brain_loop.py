import asyncio
import json

from types import SimpleNamespace as NS

import pytest

from shared.bus import results_queue
from shared.events import load_events
from shared.sessions import get_session
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


def tool_contents(calls):
    return [m["content"] for m in calls[1] if m["role"] == "tool"]


@pytest.mark.asyncio
async def test_big_tool_result_is_still_valid_json(monkeypatch):
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    big = 'say "hi"\n\\ ünï ' * 3000  # quotes/newlines/backslashes/non-ascii grow when escaped
    auto_reply(ch, results, stdout=lambda action: big)
    calls, _ = fake_client(monkeypatch, [llm_tool_calls(("git_diff", {})), llm_final("done")])

    await loop.run_session(ch, results, "s1", "diff")

    [content] = tool_contents(calls)
    assert len(content) <= 20000
    r = json.loads(content)
    assert r["exit_code"] == 0
    assert r["stderr"] == ""
    assert big.startswith(r["stdout"].split("\n[... truncated")[0])
    assert "truncated" in r["stdout"]


@pytest.mark.asyncio
async def test_small_tool_result_is_unchanged(monkeypatch):
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    auto_reply(ch, results)
    calls, _ = fake_client(monkeypatch, [llm_tool_calls(("git_status", {})), llm_final("done")])

    await loop.run_session(ch, results, "s1", "status")

    [content] = tool_contents(calls)
    assert content == json.dumps({"exit_code": 0, "stdout": "ran git.status", "stderr": ""})


def test_tool_content_trims_stdout_and_stderr():
    result = {"exit_code": 1, "stdout": "o" * 15000, "stderr": "e" * 15000, "total_lines": 7}
    content = loop.tool_content(result)
    r = json.loads(content)
    assert len(content) <= 20000
    assert r["exit_code"] == 1 and r["total_lines"] == 7
    assert r["stdout"].startswith("o" * 1000) and r["stderr"].startswith("e" * 1000)
    assert result["stdout"] == "o" * 15000  # input not mutated


def no_backoff(monkeypatch):
    """Skip the retry sleeps; returns the list of waits asked for."""
    waits, real_sleep = [], asyncio.sleep

    async def sleep(seconds):
        if seconds:
            waits.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return waits


EMPTY = [None, NS(choices=None), NS(choices=[]),
         NS(choices=None, error={"message": "upstream 502", "code": 502})]


@pytest.mark.asyncio
async def test_responses_without_choices_are_retried(monkeypatch, capsys):
    waits = no_backoff(monkeypatch)
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    calls, _ = fake_client(monkeypatch, [*EMPTY, llm_final("done")])

    await loop.run_session(ch, results, "s1", "hi")

    assert len(calls) == 5
    assert waits == [10, 20, 30, 40]
    out = capsys.readouterr().out
    assert "upstream 502" in out and "[otto] done" in out
    assert get_session("s1").status == "done"


@pytest.mark.asyncio
async def test_session_fails_with_an_error_event_after_six_empty_responses(monkeypatch):
    waits = no_backoff(monkeypatch)
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    calls, state = fake_client(monkeypatch, [*EMPTY, NS(choices=[]),
                                             NS(choices=None, error={"message": "no capacity"})])

    with pytest.raises(loop.LLMError):
        await loop.run_session(ch, results, "s1", "hi")

    assert len(calls) == 6
    assert waits == [10, 20, 30, 40, 50]
    assert get_session("s1").status == "failed"
    [err] = [e.payload for e in load_events("s1") if e.type == "error"]
    assert err["stage"] == "llm"
    assert "6 attempts" in err["message"] and "no capacity" in err["message"]
    assert state["closed"]
