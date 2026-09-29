import pytest

from shared import config
from shared.bus import results_queue
from shared.events import load_events
from shared.sessions import create_session, get_session, set_status
from brain import loop, main as brain_main
from brain.tools import SYSTEM
from tests.fakes import FakeChannel, auto_reply, llm_tool_calls, llm_final
from tests.test_brain_loop import fake_client


def bus(sid):
    ch = FakeChannel()
    results = ch.queue(results_queue(sid))
    auto_reply(ch, results)
    return ch, results


@pytest.mark.asyncio
async def test_start_session_runs_an_existing_row(monkeypatch):
    create_session("abc123", task="fix it", repo_url="https://github.com/o/r", model="m", status="running")
    ch, results = bus("abc123")
    fake_client(monkeypatch, [llm_final("done")])

    messages = await loop.start_session(ch, results, "abc123", "fix it")

    assert messages[:2] == [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "fix it"}]
    types = [e.type for e in load_events("abc123")]
    assert types.count("session.created") == 1
    assert get_session("abc123").status == "done"
    assert get_session("abc123").repo_url == "https://github.com/o/r"


@pytest.mark.asyncio
async def test_a_stopped_session_ends_after_the_current_step(monkeypatch):
    create_session("abc123", task="t", repo_url=None, model="m", status="running")
    ch, results = bus("abc123")
    replied = ch.default_exchange.on_publish

    def stop_then_reply(key, action):
        set_status("abc123", "stopped")  # DELETE /sessions/{id} while the model works
        replied(key, action)

    ch.default_exchange.on_publish = stop_then_reply
    calls, _ = fake_client(monkeypatch, [llm_tool_calls(("git_status", {})), llm_final("never asked")])

    await loop.start_session(ch, results, "abc123", "t")

    assert len(calls) == 1  # no further LLM call once stopped
    assert get_session("abc123").status == "stopped"  # not overwritten with done


@pytest.mark.asyncio
async def test_failure_does_not_override_stopped(monkeypatch):
    create_session("abc123", task="t", repo_url=None, model="m", status="running")
    ch, results = bus("abc123")

    class Boom(Exception):
        pass

    async def explode(*a, **kw):
        set_status("abc123", "stopped")
        raise Boom()

    fake_client(monkeypatch, [])
    monkeypatch.setattr(loop, "complete", explode)
    with pytest.raises(Boom):
        await loop.start_session(ch, results, "abc123", "t")
    assert get_session("abc123").status == "stopped"


def test_cli_session_flag(monkeypatch, capsys):
    create_session("other1", task="t", repo_url=None, model="m")
    brain_main.main(["--show", "--session", "other1"])
    assert capsys.readouterr().out.startswith("session other1")
    brain_main.main(["--show"])
    assert f"no session {config.SESSION_ID!r}" in capsys.readouterr().out
