import asyncio
import json

import pytest

from shared.bus import SESSIONS_QUEUE, chat_job, make_result, resume_job, results_queue, retry_job, start_job
from shared.events import load_events
from shared.sessions import create_session, get_session, transition
from brain import loop, providers, worker
from tests.fakes import FakeChannel, FakeConnection, llm_tool_calls, llm_final


def fake_llm(monkeypatch, scripts, delay=0.01):
    """Responses per session, picked by the conversation's first user message (its task)."""
    state = {"active": 0, "max_active": 0, "calls": []}

    class Completions:
        async def create(self, **kw):
            task = next(m["content"] for m in kw["messages"] if m["role"] == "user")
            state["calls"].append(task)
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            try:
                await asyncio.sleep(delay)
                return scripts[task].pop(0)
            finally:
                state["active"] -= 1

    class Client:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(providers, "AsyncOpenAI", Client)
    providers.reset()
    return state


def fake_bus():
    """One fake channel for everything; a fake runner per session echoes '<sid>:<path or cmd>'."""
    ch = FakeChannel()

    def on_publish(key, body):
        if key.endswith(".actions"):
            sid = body["session_id"]
            arg = body["payload"].get("path") or body["payload"].get("cmd") or ""
            ch.queue(results_queue(sid)).put(
                make_result(body, True, {"exit_code": 0, "stdout": f"{sid}:{arg}", "stderr": ""}))

    ch.default_exchange.on_publish = on_publish
    return ch, FakeConnection(ch)


async def run_worker(ch, conn, jobs, concurrency=3):
    q = ch.queue(SESSIONS_QUEUE)
    msgs = [q.put(job) for job in jobs]
    q.close()  # the fake iterator ends once these are taken
    await asyncio.wait_for(worker.consume(conn, q, concurrency), 5)
    return msgs


def session(sid, task, status="queued"):
    create_session(sid, task=task, repo="o/r", model="m", status=status)


@pytest.mark.asyncio
async def test_two_sessions_run_concurrently_without_crosstalk(monkeypatch):
    session("aaaa", "task A")
    session("bbbb", "task B")
    state = fake_llm(monkeypatch, {
        "task A": [llm_tool_calls(("fs_read", {"path": "a.py"})),
                   llm_tool_calls(("fs_read", {"path": "a2.py"})), llm_final("A done")],
        "task B": [llm_tool_calls(("shell_exec", {"cmd": "echo b"})), llm_final("B done")],
    })
    ch, conn = fake_bus()

    msgs = await run_worker(ch, conn, [start_job("aaaa"), start_job("bbbb")])

    assert all(m.acked for m in msgs)
    assert state["max_active"] == 2  # both sessions were talking to the model at once
    assert get_session("aaaa").status == get_session("bbbb").status == "done"

    for sid, expected in (("aaaa", ["aaaa:a.py", "aaaa:a2.py"]), ("bbbb", ["bbbb:echo b"])):
        evs = load_events(sid)
        stdouts = [e.payload["payload"]["stdout"] for e in evs if e.type == "bus.result"]
        # bbbb ran a command, so its turn ends with the finish's git.status (no path or cmd: "bbbb:")
        assert stdouts == expected + ([f"{sid}:"] if sid == "bbbb" else [])
        tools = [m["content"] for m in (e.payload["message"] for e in evs if e.type == "llm.message")
                 if m["role"] == "tool"]
        assert [json.loads(c)["stdout"] for c in tools] == expected

    kinds = [(key, body.get("kind")) for key, body in ch.default_exchange.published]
    assert ("otto.aaaa.actions", "fs.read") in kinds and ("otto.bbbb.actions", "shell.exec") in kinds
    assert all(kind != "control.shutdown" for _, kind in kinds)  # sandboxes stay warm


@pytest.mark.asyncio
async def test_concurrency_limit(monkeypatch):
    for sid in ("aaaa", "bbbb", "cccc"):
        session(sid, f"task {sid}")
    state = fake_llm(monkeypatch, {f"task {sid}": [llm_final("ok")] for sid in ("aaaa", "bbbb", "cccc")})
    ch, conn = fake_bus()

    await run_worker(ch, conn, [start_job(s) for s in ("aaaa", "bbbb", "cccc")], concurrency=2)

    assert state["max_active"] == 2
    assert {get_session(s).status for s in ("aaaa", "bbbb", "cccc")} == {"done"}


@pytest.mark.asyncio
async def test_resume_job_continues_the_conversation(monkeypatch):
    session("aaaa", "task A")
    fake_llm(monkeypatch, {"task A": [llm_final("first"), llm_final("second")]})
    ch, conn = fake_bus()
    await run_worker(ch, conn, [start_job("aaaa")])

    assert transition("aaaa", "queued", {"done"})  # as the gateway does before publishing a resume
    await run_worker(ch, conn, [resume_job("aaaa", "and then?")])

    msgs = [e.payload["message"] for e in load_events("aaaa") if e.type == "llm.message"]
    assert [m["content"] for m in msgs[1:]] == ["task A", "first", "and then?", "second"]
    assert get_session("aaaa").status == "done"


@pytest.mark.asyncio
async def test_jobs_for_sessions_that_are_not_queued_are_acked_and_skipped(monkeypatch):
    session("aaaa", "task A", status="stopped")
    state = fake_llm(monkeypatch, {})
    ch, conn = fake_bus()

    msgs = await run_worker(ch, conn, [start_job("aaaa"), start_job("ghost"), b"junk", {"type": "start"}])

    assert all(m.acked for m in msgs)
    assert state["calls"] == []
    assert get_session("aaaa").status == "stopped"


@pytest.mark.asyncio
async def test_failing_session_is_marked_failed_and_the_worker_goes_on(monkeypatch):
    session("aaaa", "task A")
    session("bbbb", "task B")
    fake_llm(monkeypatch, {"task A": [], "task B": [llm_final("ok")]})  # A's LLM call raises
    ch, conn = fake_bus()

    await run_worker(ch, conn, [start_job("aaaa"), start_job("bbbb")])

    assert get_session("aaaa").status == "failed"
    assert get_session("bbbb").status == "done"


@pytest.mark.asyncio
async def test_a_session_deleted_during_its_turn_ends_quietly(monkeypatch, capsys):
    from shared.sessions import delete_session

    session("aaaa", "task A")
    session("bbbb", "task B")
    real = worker.run_job

    async def deleted_meanwhile(conn, job):
        if job["session_id"] == "aaaa":
            delete_session("aaaa")  # DELETE /sessions/aaaa while it runs
            raise RuntimeError("its events have nowhere to go")
        await real(conn, job)

    monkeypatch.setattr(worker, "run_job", deleted_meanwhile)
    fake_llm(monkeypatch, {"task B": [llm_final("ok")]})
    ch, conn = fake_bus()

    await run_worker(ch, conn, [start_job("aaaa"), start_job("bbbb")])

    assert get_session("aaaa") is None
    assert get_session("bbbb").status == "done"
    assert "session aaaa was deleted" in capsys.readouterr().out


# --- retry: the error card's Retry continues the turn, with no new message ---------------------

def user_and_assistant(sid):
    msgs = [e.payload["message"] for e in load_events(sid) if e.type == "llm.message"]
    return [(m["role"], m["content"]) for m in msgs if m["role"] in ("user", "assistant")]


@pytest.mark.asyncio
async def test_retry_continues_a_failed_turn_without_a_new_message(monkeypatch):
    session("aaaa", "task A")
    script = {"task A": []}  # the first LLM call raises
    fake_llm(monkeypatch, script)
    ch, conn = fake_bus()
    await run_worker(ch, conn, [start_job("aaaa")])
    assert get_session("aaaa").status == "failed"

    script["task A"].append(llm_final("fixed it"))
    assert transition("aaaa", "queued", {"failed"})  # as the gateway does
    await run_worker(ch, conn, [retry_job("aaaa")])

    assert user_and_assistant("aaaa") == [("user", "task A"), ("assistant", "fixed it")]
    assert get_session("aaaa").status == "done"


@pytest.mark.asyncio
async def test_retry_of_a_session_that_never_started_runs_its_task(monkeypatch):
    session("aaaa", "task A")  # e.g. its sandbox failed to start: no conversation yet
    fake_llm(monkeypatch, {"task A": [llm_final("done")]})
    ch, conn = fake_bus()

    await run_worker(ch, conn, [retry_job("aaaa")])

    assert user_and_assistant("aaaa") == [("user", "task A"), ("assistant", "done")]


@pytest.mark.asyncio
async def test_retry_of_a_plain_chat_answers_again(monkeypatch):
    create_session("cccc", task="what is a closure?", repo=None, model="m", status="queued")
    script = {"what is a closure?": []}
    fake_llm(monkeypatch, script)
    ch, conn = fake_bus()
    await run_worker(ch, conn, [chat_job("cccc")])
    assert get_session("cccc").status == "failed"

    script["what is a closure?"].append(llm_final("A function with its scope."))
    assert transition("cccc", "queued", {"failed"})
    await run_worker(ch, conn, [retry_job("cccc")])

    assert user_and_assistant("cccc") == [("user", "what is a closure?"), ("assistant", "A function with its scope.")]
    assert ch.default_exchange.published == [] or all(not k.endswith(".actions") for k, _ in ch.default_exchange.published)


def test_retry_jobs_parse():
    assert worker.parse_job(json.dumps({"type": "retry", "session_id": "s"})) == {"type": "retry", "session_id": "s"}
    assert worker.parse_job(json.dumps({"type": "retry"})) is None


@pytest.mark.asyncio
async def test_a_follow_up_the_gateway_stored_already_is_not_added_again(monkeypatch):
    from brain.resume import rebuild_messages
    from shared.events import append_event

    session("aaaa", "task A")
    fake_llm(monkeypatch, {"task A": [llm_final("first"), llm_final("second")]})
    ch, conn = fake_bus()
    await run_worker(ch, conn, [start_job("aaaa")])

    assert transition("aaaa", "queued", {"done"})
    append_event("aaaa", "llm.message", {"message": {"role": "user", "content": "and then?"}})  # as the gateway does
    await run_worker(ch, conn, [resume_job("aaaa", "and then?")])

    msgs = [e.payload["message"] for e in load_events("aaaa") if e.type == "llm.message"]
    assert [m["content"] for m in msgs[1:]] == ["task A", "first", "and then?", "second"]
    users = [m for m in rebuild_messages(load_events("aaaa")) if m["role"] == "user"]
    assert [m["content"] for m in users] == ["task A", "and then?"]
