"""The end of an agent turn: whatever the model left undone, the brain commits, pushes and opens
the PR, with ordinary bus actions (so each step is an event row like any other)."""
import asyncio

import pytest

from shared.bus import make_result, results_queue
from shared.events import load_events
from shared.models import make_title
from shared.sessions import create_session, get_session, record_pr
from brain import loop
from tests.fakes import FakeChannel, llm_final, llm_tool_calls
from tests.test_brain_loop import fake_client

TASK = "two tests are failing, find out why and fix the source, not the tests"
PR_URL = "https://github.com/o/r/pull/5"


class Runner:
    """A fake sandbox that keeps the git state the finish looks at: uncommitted changes, commits
    not on the remote, and the branch's commits. fail: a kind whose action fails."""

    def __init__(self, ch, results, dirty=False, ahead=0, work=0, fail=None):
        self.git = {"dirty": dirty, "ahead": ahead, "work": work}
        self.actions = []
        self.fail = fail
        self.results = results
        ch.default_exchange.on_publish = self.on_publish

    @property
    def kinds(self):
        return [a["kind"] for a in self.actions]

    def on_publish(self, key, action):
        kind, g = action["kind"], self.git
        self.actions.append(action)
        out = {"exit_code": 0, "stdout": f"ran {kind}", "stderr": ""}
        if kind == self.fail:
            out = {"exit_code": 1, "stdout": "", "stderr": f"{kind} failed: rejected"}
        elif kind in ("fs.replace", "fs.write"):
            g["dirty"] = True
        elif kind == "git.status":
            out.update(dirty=g["dirty"], ahead=g["ahead"], work=g["work"], base="main")
        elif kind == "git.commit" and g["dirty"]:
            g.update(dirty=False, ahead=g["ahead"] + 1, work=g["work"] + 1)
        elif kind == "git.push":
            g["ahead"] = 0
            out.update(branch="otto/s1", base="main")
        elif kind == "git.open_pr":
            out.update(number=5, html_url=PR_URL, title=action["payload"]["title"], base="main")
        self.results.put(make_result(action, out["exit_code"] == 0, out))


def setup(monkeypatch, responses, **git):
    ch = FakeChannel()
    results = ch.queue(results_queue("s1"))
    runner = Runner(ch, results, **git)
    fake_client(monkeypatch, responses)
    create_session("s1", task=TASK, repo="o/r", model="m", status="running")
    return ch, results, runner


async def run(ch, results):
    try:
        await asyncio.wait_for(loop.start_session(ch, results, "s1", TASK), 5)
    except Exception:
        pass  # a failed turn raises as before; the status and events tell the story


def payload(runner, kind):
    return next(a["payload"] for a in runner.actions if a["kind"] == kind)


EDIT = ("fs_replace", {"path": "src/p.py", "old_str": ">", "new_str": ">="})


@pytest.mark.asyncio
async def test_changes_but_no_pr_commit_push_and_open(monkeypatch):
    ch, results, runner = setup(monkeypatch, [llm_tool_calls(EDIT), llm_final("Fixed the threshold: `>` is now `>=`.")])

    await run(ch, results)

    assert runner.kinds == ["fs.replace", "git.status", "git.commit", "git.push", "git.open_pr"]
    assert payload(runner, "git.commit") == {"message": make_title(TASK)}
    assert payload(runner, "git.open_pr") == {"title": make_title(TASK), "body": "Fixed the threshold: `>` is now `>=`."}
    row = get_session("s1")
    assert (row.status, row.pr_url) == ("done", PR_URL)
    types = [e.type for e in load_events("s1")]
    assert types.count("bus.action") == 5 and "pr.opened" in types
    # the finish happens after the model's final message
    assert types.index("pr.opened") > max(i for i, e in enumerate(load_events("s1"))
                                          if e.type == "llm.message" and e.payload["message"]["role"] == "assistant")


@pytest.mark.asyncio
async def test_the_model_already_opened_the_pr_no_duplicate(monkeypatch):
    ch, results, runner = setup(monkeypatch, [
        llm_tool_calls(EDIT),
        llm_tool_calls(("git_commit", {"message": "Fix"}), ("git_push", {})),
        llm_tool_calls(("git_open_pr", {"title": "Fix", "body": "b"})),
        llm_final("Done, PR #5."),
    ])

    await run(ch, results)

    assert runner.kinds == ["fs.replace", "git.commit", "git.push", "git.open_pr", "git.status"]
    assert runner.kinds.count("git.open_pr") == 1
    assert get_session("s1").status == "done"


@pytest.mark.asyncio
async def test_a_follow_up_on_an_open_pr_pushes_but_opens_nothing(monkeypatch):
    ch, results, runner = setup(monkeypatch, [llm_tool_calls(EDIT), llm_final("Added the test.")], work=1)
    record_pr("s1", 5, PR_URL)  # an earlier turn's PR

    await run(ch, results)

    assert runner.kinds == ["fs.replace", "git.status", "git.commit", "git.push"]


@pytest.mark.asyncio
async def test_pushed_but_no_pr_opens_one(monkeypatch):
    # what a weaker model does: commit and push, then stop without the PR
    ch, results, runner = setup(monkeypatch, [
        llm_tool_calls(EDIT),
        llm_tool_calls(("git_commit", {"message": "Fix"}), ("git_push", {})),
        llm_final("Committed and pushed."),
    ])

    await run(ch, results)

    assert runner.kinds == ["fs.replace", "git.commit", "git.push", "git.status", "git.open_pr"]
    assert get_session("s1").pr_url == PR_URL


@pytest.mark.asyncio
async def test_no_changes_nothing(monkeypatch):
    ch, results, runner = setup(monkeypatch, [
        llm_tool_calls(("fs_read", {"path": "a.py"}), ("code_search", {"pattern": "x"})),
        llm_final("The pricing is computed in a.py."),
    ], work=0)

    await run(ch, results)

    assert runner.kinds == ["fs.read", "code.search"]  # not even a status check
    assert get_session("s1").status == "done"


@pytest.mark.asyncio
async def test_commands_that_change_nothing_finish_with_just_the_status(monkeypatch):
    ch, results, runner = setup(monkeypatch, [llm_tool_calls(("shell_exec", {"cmd": "pytest -q"})), llm_final("All pass.")])

    await run(ch, results)

    assert runner.kinds == ["shell.exec", "git.status"]
    assert get_session("s1").status == "done"


@pytest.mark.asyncio
async def test_push_fails_error_and_failed(monkeypatch):
    ch, results, runner = setup(monkeypatch, [llm_tool_calls(EDIT), llm_final("Fixed.")], fail="git.push")

    await run(ch, results)

    assert runner.kinds == ["fs.replace", "git.status", "git.commit", "git.push"]  # no PR after a failed push
    assert get_session("s1").status == "failed"
    [err] = [e.payload for e in load_events("s1") if e.type == "error"]
    assert err["stage"] == "finish" and "git.push failed: rejected" in err["message"]


@pytest.mark.asyncio
async def test_a_stopped_turn_is_not_finished(monkeypatch):
    ch, results, runner = setup(monkeypatch, [llm_tool_calls(EDIT), llm_final("never")])
    real = loop._stopped
    calls = {"n": 0}

    def stopped_after_first_step(sid):
        calls["n"] += 1
        return calls["n"] > 1 or real(sid)

    monkeypatch.setattr(loop, "_stopped", stopped_after_first_step)

    await run(ch, results)

    assert runner.kinds == ["fs.replace"]


@pytest.mark.asyncio
async def test_plain_chats_have_no_finish(monkeypatch):
    fake_client(monkeypatch, [llm_final("A function with its scope.")])
    create_session("c1", task="what is a closure?", repo=None, model="m", status="running")

    await loop.chat_session("c1")

    assert not [e for e in load_events("c1") if e.type.startswith("bus.")]
    assert get_session("c1").status == "done"
