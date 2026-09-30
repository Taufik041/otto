import json

import pytest

from shared import config
from shared.bus import make_result, results_queue
from shared.events import load_events
from shared.sessions import get_session
from brain import loop, main as brain_main
from brain.tools import KIND, SYSTEM, TOOLS
from tests.fakes import FakeChannel, llm_tool_calls, llm_final
from tests.test_brain_loop import fake_client

TOKEN = "ghs_LeakedInstallationToken99"
PR = {"number": 3, "html_url": "https://github.com/Taufik041/otto_test/pull/3"}


def runner(replies):
    """A fake channel whose runner answers each action kind with replies[kind]."""
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))

    def on_publish(key, action):
        payload = replies[action["kind"]]
        results.put(make_result(action, payload["exit_code"] == 0, payload))

    ch.default_exchange.on_publish = on_publish
    return ch, results


def ok(**extra):
    return {"exit_code": 0, "stdout": "", "stderr": "", **extra}


@pytest.mark.asyncio
async def test_opened_pr_is_recorded(monkeypatch):
    ch, results = runner({"git.push": ok(branch="otto/s1"),
                          "git.open_pr": ok(stdout=PR["html_url"], **PR)})
    fake_client(monkeypatch, [
        llm_tool_calls(("git_push", {})),
        llm_tool_calls(("git_open_pr", {"title": "Fix", "body": "root cause, fix, tests"})),
        llm_final("PR opened"),
    ])

    await loop.run_session(ch, results, "s1", "fix it")

    evs = load_events("s1")
    types = [e.type for e in evs]
    i = types.index("pr.opened")
    assert types[i - 1] == "bus.result" and types[i + 1] == "llm.message"
    assert evs[i].payload == PR
    row = get_session("s1")
    assert (row.pr_url, row.work_branch) == (PR["html_url"], "otto/s1")


@pytest.mark.asyncio
async def test_failed_pr_is_not_recorded(monkeypatch):
    ch, results = runner({"git.open_pr": {"exit_code": 1, "stdout": "",
                                          "stderr": "GitHub API 422: No commits between main and otto/s1"}})
    fake_client(monkeypatch, [llm_tool_calls(("git_open_pr", {"title": "t", "body": "b"})), llm_final("no")])

    await loop.run_session(ch, results, "s1", "fix it")

    assert "pr.opened" not in [e.type for e in load_events("s1")]
    assert get_session("s1").pr_url is None


@pytest.mark.asyncio
async def test_token_never_reaches_stored_events(monkeypatch):
    # even if a runner result leaked it, the event log must not keep the token
    leak = {"exit_code": 128, "stdout": "",
            "stderr": f"fatal: could not read from https://x-access-token:{TOKEN}@github.com/o/r: {TOKEN}"}
    ch, results = runner({"git.push": leak})
    fake_client(monkeypatch, [llm_tool_calls(("git_push", {})), llm_final("push failed")])

    await loop.run_session(ch, results, "s1", "push it")

    stored = json.dumps([e.payload for e in load_events("s1")])
    assert TOKEN not in stored
    assert "[REDACTED]" in stored


def test_show_prints_branch_and_pr(monkeypatch, capsys):
    from shared.sessions import create_session, record_pr
    create_session(config.SESSION_ID, task="t", repo_url=None, model="m")
    record_pr(config.SESSION_ID, PR["number"], PR["html_url"])

    brain_main.main(["--show"])

    out = capsys.readouterr().out
    assert f"branch: otto/{config.SESSION_ID}" in out and f"pr: {PR['html_url']}" in out
    assert any("pr.opened" in l and "#3" in l for l in out.splitlines())


def test_tools_and_prompt():
    names = [t["function"]["name"] for t in TOOLS]
    assert "git_push" in names and "git_open_pr" in names
    pr_tool = next(t for t in TOOLS if t["function"]["name"] == "git_open_pr")
    assert pr_tool["function"]["parameters"]["required"] == ["title", "body"]
    assert KIND["git_push"] == "git.push" and KIND["git_open_pr"] == "git.open_pr"
    assert SYSTEM.startswith("You are Otto, an autonomous coding agent")
    assert "git_commit with a short message" in SYSTEM  # the existing text is kept
    assert "git_push" in SYSTEM and "git_open_pr" in SYSTEM
