import asyncio
import json

from types import SimpleNamespace as NS

import pytest

import httpx2
from openai import RateLimitError

from shared import config
from shared.bus import results_queue
from shared.events import load_events
from shared.sessions import create_session, get_session
from brain import loop, providers
from tests.fakes import FakeChannel, auto_reply, fake_clock, fake_openai, llm_tool_calls, llm_final, use_env


def fake_client(monkeypatch, responses, delay=0):
    """Patch the providers' AsyncOpenAI client; returns the list of messages sent per call, and
    state["clients"]: the arguments each client was built with."""
    calls = []
    state = {"clients": []}

    class Completions:
        async def create(self, **kw):
            calls.append(json.loads(json.dumps(kw["messages"], default=str)))
            state.setdefault("tools", []).append(kw.get("tools"))
            await asyncio.sleep(delay)
            return responses.pop(0)

    class Client:
        def __init__(self, **kw):
            state["clients"].append(kw)
            self.chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(providers, "AsyncOpenAI", Client)
    providers.reset()  # pools cache their clients
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
    assert state["clients"] == [{"api_key": "or-test-key-1", "base_url": "https://openrouter.ai/api/v1",
                                 "max_retries": 0, "timeout": 120.0}]


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


EMPTY = [None, NS(choices=None), NS(choices=[]),
         NS(choices=None, error={"message": "upstream 502", "code": 502})]


@pytest.mark.asyncio
async def test_responses_without_choices_are_retried(monkeypatch, capsys):
    monkeypatch.setattr(config, "MODEL_WAIT_BUDGET_SECONDS", 10_000)  # about the attempt cap, not the wait budget
    waits = fake_clock(monkeypatch)
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    calls, _ = fake_client(monkeypatch, [*EMPTY, llm_final("done")])

    await loop.run_session(ch, results, "s1", "hi")

    assert len(calls) == 6  # five tries for the turn, then the auto title's call (no response left: no title)
    assert waits == [60, 60, 60, 60]  # one key: it rests 60s after each
    out = capsys.readouterr().out
    assert "upstream 502" in out and "[otto] done" in out
    assert get_session("s1").status == "done"


@pytest.mark.asyncio
async def test_session_fails_with_an_error_event_after_six_empty_responses(monkeypatch):
    monkeypatch.setattr(config, "MODEL_WAIT_BUDGET_SECONDS", 10_000)  # about the attempt cap, not the wait budget
    waits = fake_clock(monkeypatch)
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    calls, state = fake_client(monkeypatch, [*EMPTY, NS(choices=[]),
                                             NS(choices=None, error={"message": "no capacity"})])

    with pytest.raises(loop.LLMError):
        await loop.run_session(ch, results, "s1", "hi")

    assert len(calls) == 6
    assert waits == [60] * 5
    assert get_session("s1").status == "failed"
    [err] = [e.payload for e in load_events("s1") if e.type == "error"]
    assert err["stage"] == "llm"
    assert "6 attempts" in err["message"] and "no capacity" in err["message"]


def rate_limited():
    req = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return RateLimitError("429", response=httpx2.Response(429, request=req), body=None)


@pytest.mark.asyncio
async def test_endless_rate_limits_fail_the_session_with_an_error_event(monkeypatch):
    monkeypatch.setattr(config, "MODEL_WAIT_BUDGET_SECONDS", 10_000)  # about the attempt cap, not the wait budget
    fake_clock(monkeypatch)
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    calls = fake_openai(monkeypatch, {"or-test-key-1": [rate_limited() for _ in range(6)]})

    with pytest.raises(loop.LLMError):
        await loop.run_session(ch, results, "s1", "hi")

    assert len(calls) == 6
    assert get_session("s1").status == "failed"
    [err] = [e.payload for e in load_events("s1") if e.type == "error"]
    assert err == {"stage": "llm", "message": "no usable LLM response after 6 attempts; last: rate limited"}


# --- providers -----------------------------------------------------------------

TWO_PROVIDERS = {"OPENROUTER_API_KEY": "orkey-one", "OPENROUTER_API_KEY2": "orkey-two",
                 "OPENAI_API_KEY": "oaikey-one", "OTTO_OPENAI_MODELS": "model-a"}


@pytest.mark.asyncio
async def test_session_runs_on_its_models_provider(monkeypatch):
    use_env(monkeypatch, TWO_PROVIDERS)
    create_session("s1", task="hi", repo=None, model="openai:model-a", status="queued")
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    calls = fake_openai(monkeypatch, {"oaikey-one": [llm_final("done"), llm_final("Greeting")]})

    await loop.start_session(ch, results, "s1", "hi")

    # the turn, then its auto title: both on the session's provider and model
    assert [(c["base_url"], c["api_key"], c["model"]) for c in calls] == [
        ("https://api.openai.com/v1", "oaikey-one", "model-a")] * 2


@pytest.mark.asyncio
async def test_follow_up_keeps_the_sessions_model(monkeypatch):
    use_env(monkeypatch, TWO_PROVIDERS)
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    calls = fake_openai(monkeypatch, {"orkey-one": [llm_final("hello"), llm_final("Greeting"), llm_final("again")],
                                      "oaikey-one": []})
    await loop.run_session(ch, results, "s1", "hi")
    assert get_session("s1").model == "openrouter:openrouter/free"

    monkeypatch.setattr(config, "DEFAULT_MODEL", "openai:model-a")  # the default changed meanwhile
    await loop.resume_session(ch, results, "s1", "more")

    # the first turn, its auto title, the follow-up: all on the session's model
    assert [(c["base_url"], c["model"]) for c in calls] == [("https://openrouter.ai/api/v1", "openrouter/free")] * 3


@pytest.mark.asyncio
async def test_key_rotation_is_in_the_session_log_without_keys(monkeypatch):
    fake_clock(monkeypatch)
    use_env(monkeypatch, TWO_PROVIDERS)
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    calls = fake_openai(monkeypatch, {"orkey-one": [rate_limited()], "orkey-two": [llm_final("done")],
                                      "oaikey-one": []})

    await loop.run_session(ch, results, "s1", "hi")

    [rotated] = [e.payload for e in load_events("s1") if e.type == "llm.key_rotated"]
    assert rotated == {"provider": "openrouter", "from_index": 0, "to_index": 1, "reason": "rate_limited"}
    log = json.dumps([e.payload for e in load_events("s1")])
    assert "orkey-" not in log and "oaikey-" not in log
    assert {c["base_url"] for c in calls} == {"https://openrouter.ai/api/v1"}


@pytest.mark.asyncio
async def test_missing_required_parameter_is_answered_without_the_bus(monkeypatch):
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    auto_reply(ch, results)
    calls, _ = fake_client(monkeypatch, [
        llm_tool_calls(("shell_exec", {}), ("fs_replace", {"path": "a.py"}), ("git_status", {})),
        llm_final("done"),
    ])

    await loop.run_session(ch, results, "s1", "fix it")

    assert [a["kind"] for _, a in ch.default_exchange.published] == ["git.status"]
    assert [json.loads(c) for c in tool_contents(calls)] == [
        {"exit_code": 1, "stdout": "",
         "stderr": "missing required parameter(s): cmd. shell_exec takes: cmd"},
        {"exit_code": 1, "stdout": "",
         "stderr": "missing required parameter(s): old_str, new_str. fs_replace takes: path, old_str, new_str"},
        {"exit_code": 0, "stdout": "ran git.status", "stderr": ""},
    ]


def test_tool_content_leaves_out_what_only_the_ui_shows():
    # the runner adds diffs and stats for the UI (stored in bus.result); the model sees what it always did
    result = {"exit_code": 0, "stdout": "replaced 1 occurrence in /workspace/a.py", "stderr": "",
              "diff": "--- a/a.py\n+++ b/a.py\n", "diff_truncated": True, "added": 1, "removed": 1,
              "created": False, "diffstat": {"files": 1, "additions": 1, "deletions": 1}, "base": "main",
              "title": "Fix", "number": 3, "html_url": "u", "branch": "otto/s1",
              "dirty": True, "ahead": 1, "work": 2}
    assert json.loads(loop.tool_content(result)) == {
        "exit_code": 0, "stdout": "replaced 1 occurrence in /workspace/a.py", "stderr": "",
        "number": 3, "html_url": "u", "branch": "otto/s1"}
