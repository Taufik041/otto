import asyncio
import json

import pytest

from shared.bus import results_queue
from shared.events import load_events
from shared.sessions import get_session
from brain import loop
from brain.resume import INTERRUPTED, rebuild_messages
from brain.tools import SYSTEM
from tests.fakes import FakeChannel, auto_reply, llm_tool_calls, llm_final
from tests.test_brain_loop import fake_client


def bus(sid="s1", answer=True):
    ch = FakeChannel()
    results = ch.queue(results_queue(sid))
    if answer:
        auto_reply(ch, results)
    return ch, results


def types(sid="s1"):
    return [e.type for e in load_events(sid)]


def llm_messages(sid="s1"):
    return [e.payload["message"] for e in load_events(sid) if e.type == "llm.message"]


@pytest.mark.asyncio
async def test_rebuild_round_trip_after_two_tool_turns(monkeypatch):
    ch, results = bus()
    calls, _ = fake_client(monkeypatch, [
        llm_tool_calls(("git_status", {}), ("fs_read", {"path": "a.py"}), content="looking"),
        llm_tool_calls(("fs_replace", {"path": "a.py", "old_str": "x", "new_str": "y"})),
        llm_final("changed x to y"),
    ])

    messages = await loop.run_session(ch, results, "s1", "fix it")

    assert rebuild_messages(load_events("s1")) == messages
    # exactly what the model was sent, plus its final answer
    assert messages == calls[-1] + [{"role": "assistant", "content": "changed x to y"}]
    assert messages[:2] == [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "fix it"}]
    assert [m["role"] for m in messages] == [
        "system", "user", "assistant", "tool", "tool", "assistant", "tool", "assistant"]

    assert types() == [
        "session.created", "llm.message", "llm.message", "session.status",
        "llm.message", "bus.action", "bus.result", "llm.message", "bus.action", "bus.result", "llm.message",
        "llm.message", "bus.action", "bus.result", "llm.message",
        "llm.message", "session.status"]
    evs = load_events("s1")
    assert [e.seq for e in evs] == list(range(1, len(evs) + 1))
    assert evs[0].payload == {"task": "fix it", "repo": None, "model": "openrouter:openrouter/free"}
    action, result = evs[5].payload, evs[6].payload
    assert action["kind"] == "git.status" and result["action_id"] == action["action_id"]
    assert result["ok"] is True and result["payload"]["stdout"] == "ran git.status"
    assert [e.payload["status"] for e in evs if e.type == "session.status"] == ["running", "done"]
    assert get_session("s1").status == "done"


@pytest.mark.asyncio
async def test_llm_error_marks_session_failed(monkeypatch):
    ch, results = bus()
    fake_client(monkeypatch, [])  # pop from an empty list: the "LLM call" raises

    with pytest.raises(IndexError):
        await loop.run_session(ch, results, "s1", "fix it")

    assert get_session("s1").status == "failed"
    assert types()[-1] == "session.status"


@pytest.mark.asyncio
async def test_cancel_mid_turn_then_resume(monkeypatch):
    ch, results = bus(answer=False)  # the runner never answers
    fake_client(monkeypatch, [llm_tool_calls(("git_status", {}))])

    task = asyncio.ensure_future(loop.run_session(ch, results, "s1", "fix it"))
    for _ in range(1000):
        if ch.default_exchange.published:
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert get_session("s1").status == "interrupted"
    assert types()[-3:] == ["llm.message", "bus.action", "session.status"]
    rebuilt = rebuild_messages(load_events("s1"))
    assert rebuilt[-1] == {"role": "tool", "tool_call_id": "call_0", "content": json.dumps(INTERRUPTED)}

    # resume: same session, seq continues, the model sees the whole conversation
    last_seq = load_events("s1")[-1].seq
    ch, results = bus()
    calls, _ = fake_client(monkeypatch, [llm_final("I checked git status")])

    messages = await loop.resume_session(ch, results, "s1", "what did you do?")

    new = load_events("s1")[last_seq:]
    assert [e.seq for e in new] == list(range(last_seq + 1, last_seq + 1 + len(new)))
    assert [e.type for e in new] == ["llm.message", "llm.message", "session.status",
                                     "llm.message", "session.status"]
    assert calls[0] == rebuilt + [{"role": "user", "content": "what did you do?"}]
    # the synthetic result is stored too, so the log matches what the model saw
    assert llm_messages() == messages
    assert rebuild_messages(load_events("s1")) == messages
    assert get_session("s1").status == "done"


@pytest.mark.asyncio
async def test_resume_after_a_finished_session(monkeypatch):
    ch, results = bus()
    fake_client(monkeypatch, [llm_final("hello")])
    first = await loop.run_session(ch, results, "s1", "say hi")

    calls, _ = fake_client(monkeypatch, [llm_final("I said hello")])
    messages = await loop.resume_session(ch, results, "s1", "what did you say?")

    assert calls[0] == first + [{"role": "user", "content": "what did you say?"}]
    assert rebuild_messages(load_events("s1")) == messages
    assert [e.payload["status"] for e in load_events("s1") if e.type == "session.status"] == [
        "running", "done", "running", "done"]


@pytest.mark.asyncio
async def test_resume_needs_an_existing_conversation():
    ch, results = bus()
    with pytest.raises(LookupError):
        await loop.resume_session(ch, results, "nope", "hi")
