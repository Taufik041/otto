"""Plain chats (no repo, no sandbox, no tools), and turning one into an agent session."""
import asyncio
import json

import pytest

from brain import loop, providers, worker
from brain.resume import rebuild_messages
from brain.tools import CHAT_SYSTEM, SYSTEM
from shared.bus import SESSIONS_QUEUE, chat_job, resume_job, results_queue
from shared.events import load_events
from shared.sessions import attach_repo, create_session, get_session
from tests.fakes import FakeChannel, FakeConnection, auto_reply, llm_final, llm_tool_calls


def fake_llm(monkeypatch, responses):
    """Every request the model gets: {"messages": [...], "tools": ... or None}."""
    requests = []

    class Completions:
        async def create(self, **kw):
            requests.append({"messages": json.loads(json.dumps(kw["messages"])), "tools": kw.get("tools")})
            r = responses.pop(0)
            if isinstance(r, BaseException):
                raise r
            return r

    class Client:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(providers, "AsyncOpenAI", Client)
    providers.reset()
    return requests


def messages(sid):
    return [e.payload["message"] for e in load_events(sid) if e.type == "llm.message"]


def chat(sid="c1", task="what is a closure?", status="running"):
    create_session(sid, task=task, repo=None, model="openrouter:openrouter/free", status=status)
    return sid


@pytest.mark.asyncio
async def test_a_chat_turn_is_one_call_without_tools(monkeypatch):
    sid = chat()
    requests = fake_llm(monkeypatch, [llm_final("A function that captures variables.")])

    await asyncio.wait_for(loop.chat_session(sid), 2)

    [req] = requests
    assert req["tools"] is None
    assert req["messages"] == [{"role": "system", "content": CHAT_SYSTEM},
                               {"role": "user", "content": "what is a closure?"}]
    assert messages(sid)[-1] == {"role": "assistant", "content": "A function that captures variables."}
    assert get_session(sid).status == "done"


@pytest.mark.asyncio
async def test_a_chat_follow_up_continues_the_conversation(monkeypatch):
    sid = chat()
    fake_llm(monkeypatch, [llm_final("first answer")])
    await loop.chat_session(sid)
    requests = fake_llm(monkeypatch, [llm_final("second answer")])

    await loop.chat_session(sid, "and in Python?")

    assert [m["content"] for m in requests[0]["messages"]] == [
        CHAT_SYSTEM, "what is a closure?", "first answer", "and in Python?"]
    assert messages(sid)[-1]["content"] == "second answer"


@pytest.mark.asyncio
async def test_a_chat_llm_failure_marks_it_failed(monkeypatch):
    sid = chat()
    async def broken(*a, **kw):
        raise providers.LLMError("no usable LLM response after 6 attempts")

    monkeypatch.setattr(loop, "complete", broken)
    with pytest.raises(providers.LLMError):
        await loop.chat_session(sid)
    assert get_session(sid).status == "failed"
    assert [e.payload["stage"] for e in load_events(sid) if e.type == "error"] == ["llm"]


def test_the_chat_prompt_points_to_mentioning_a_repo():
    assert "@" in CHAT_SYSTEM and "repo" in CHAT_SYSTEM.lower()


def test_the_agent_prompt_keeps_to_the_task():
    assert ("Stay within the task. If unrelated tests fail, mention them in your summary "
            "instead of fixing them.") in SYSTEM


# --- the worker -----------------------------------------------------------------------

def test_parse_chat_jobs():
    assert worker.parse_job(json.dumps(chat_job("c1"))) == {"type": "chat", "session_id": "c1"}
    assert worker.parse_job(json.dumps(chat_job("c1", "more"))) == {"type": "chat", "session_id": "c1",
                                                                      "text": "more"}
    assert worker.parse_job(json.dumps({"type": "chat", "session_id": "c1", "text": 3})) is None


@pytest.mark.asyncio
async def test_the_worker_runs_chat_jobs_without_touching_the_bus(monkeypatch):
    sid = chat(status="queued")
    fake_llm(monkeypatch, [llm_final("hello!")])
    ch = FakeChannel()
    q = ch.queue(SESSIONS_QUEUE)
    msg = q.put(chat_job(sid))
    q.close()

    await asyncio.wait_for(worker.consume(FakeConnection(ch), q, 1), 2)

    assert msg.acked and get_session(sid).status == "done"
    assert set(ch.queues) == {SESSIONS_QUEUE}  # no session queues: there is no sandbox
    assert messages(sid)[-1]["content"] == "hello!"


# --- a chat that gets a repo ------------------------------------------------------------

@pytest.mark.asyncio
async def test_attaching_a_repo_switches_the_chat_to_the_agent(monkeypatch):
    sid = chat()
    fake_llm(monkeypatch, [llm_final("Mention a repo with @ and I'll work on it.")])
    await loop.chat_session(sid)
    attach_repo(sid, "Taufik041/otto_test")
    ch = FakeChannel()
    results = ch.queue(results_queue(sid))
    auto_reply(ch, results)
    requests = fake_llm(monkeypatch, [llm_tool_calls(("git_status", {})), llm_final("fixed")])

    await asyncio.wait_for(loop.resume_session(ch, results, sid, "fix the tests"), 2)

    first = requests[0]
    assert first["tools"] is not None
    assert first["messages"][0] == {"role": "system", "content": SYSTEM}  # the agent prompt, and only it
    assert [m["role"] for m in first["messages"]] == ["system", "user", "assistant", "user"]
    assert [a["kind"] for _, a in ch.default_exchange.published] == ["git.status"]
    # the log shows the switch, and replays to what the model saw
    assert [m["content"] for m in messages(sid) if m["role"] == "system"] == [CHAT_SYSTEM, SYSTEM]
    assert rebuild_messages(load_events(sid))[:4] == first["messages"]


def test_the_latest_system_message_is_the_one_in_force():
    from types import SimpleNamespace as NS

    evs = [NS(type="llm.message", payload={"message": m}) for m in [
        {"role": "system", "content": "old"}, {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"}, {"role": "system", "content": "new"},
        {"role": "user", "content": "q2"}]]
    assert rebuild_messages(evs) == [{"role": "system", "content": "new"}, {"role": "user", "content": "q"},
                                     {"role": "assistant", "content": "a"}, {"role": "user", "content": "q2"}]


def test_the_agent_prompt_requires_commit_push_and_pr_before_the_summary():
    finish = SYSTEM[SYSTEM.index("When the task is done"):]
    assert "MUST" in finish
    assert finish.index("git_commit") < finish.index("git_push") < finish.index("git_open_pr") < finish.index("final summary")
