"""Auto titles: after a chat's first completed turn, a chat still titled from its first message gets
a better one: its PR's title, or a 3-6 word title from its own model. A rename always wins."""
import pytest

from brain import loop
from shared.events import load_events
from shared.sessions import create_session, get_session, set_title
from tests.fakes import llm_final, llm_tool_calls
from tests.test_brain_chat import fake_llm
from tests.test_brain_finish import EDIT, PR_URL, run, setup


def titled(sid):
    return [e.payload for e in load_events(sid) if e.type == "session.titled"]


def usages(sid):
    return [e for e in load_events(sid) if e.type == "llm.usage"]


@pytest.mark.asyncio
async def test_an_agent_chat_with_a_proposal_takes_its_title(monkeypatch):
    from shared.events import append_event

    ch, results, runner = setup(monkeypatch, [llm_tool_calls(EDIT), llm_final("Done.")])
    real = loop.propose

    def propose_with_a_title(sid, record, messages, **kw):
        real(sid, record, messages, **kw)
        # as if the proposal had a better title than the task's first line
        append_event(sid, "pr.proposed", {**proposal(sid), "title": "Fix bulk discount threshold"})

    monkeypatch.setattr(loop, "propose", propose_with_a_title)

    await run(ch, results)

    row = get_session("s1")
    assert (row.status, row.pr_url) == ("done", None)
    assert (row.title, row.title_source) == ("Fix bulk discount threshold", "generated")
    assert titled("s1") == [{"title": "Fix bulk discount threshold", "source": "proposal"}]
    assert len(usages("s1")) == 2  # the turn's own calls only: no title call


def proposal(sid):
    return [e.payload for e in load_events(sid) if e.type == "pr.proposed"][-1]


@pytest.mark.asyncio
async def test_a_plain_chat_gets_a_short_title_from_its_model(monkeypatch):
    create_session("c1", task="hey so what is a closure, like in javascript, I never got it", repo=None,
                   model="openrouter:openrouter/free", status="running")
    requests = fake_llm(monkeypatch, [llm_final("A function that keeps its scope."), llm_final('"Closures in JavaScript."\n')])

    await loop.chat_session("c1")

    row = get_session("c1")
    assert (row.status, row.title, row.title_source) == ("done", "Closures in JavaScript", "generated")
    assert titled("c1") == [{"title": "Closures in JavaScript", "source": "model"}]
    # one short call on the chat's model, with no tools, counted in usage
    title_call = requests[1]
    assert title_call["tools"] is None and title_call["model"] == "openrouter/free"
    assert "title" in title_call["messages"][0]["content"].lower()
    assert "closure" in title_call["messages"][-1]["content"]
    assert len(usages("c1")) == 2


@pytest.mark.asyncio
async def test_a_manual_rename_is_kept(monkeypatch):
    create_session("c1", task="what is a closure?", repo=None, model="openrouter:openrouter/free", status="running")
    set_title("c1", "My closures notes")  # the user renamed it while Otto answered
    requests = fake_llm(monkeypatch, [llm_final("A function.")])

    await loop.chat_session("c1")

    row = get_session("c1")
    assert (row.title, row.title_source) == ("My closures notes", "user")
    assert len(requests) == 1 and titled("c1") == []


@pytest.mark.asyncio
async def test_a_title_failure_never_fails_the_turn(monkeypatch):
    create_session("c1", task="what is a closure?", repo=None, model="openrouter:openrouter/free", status="running")
    fake_llm(monkeypatch, [llm_final("A function."), RuntimeError("the title call blew up")])

    await loop.chat_session("c1")

    row = get_session("c1")
    assert (row.status, row.title, row.title_source) == ("done", "what is a closure?", "auto")
    assert titled("c1") == []


@pytest.mark.asyncio
async def test_only_the_first_completed_turn_is_titled(monkeypatch):
    create_session("c1", task="what is a closure?", repo=None, model="openrouter:openrouter/free", status="running")
    requests = fake_llm(monkeypatch, [llm_final("A function."), llm_final("Closures"), llm_final("def f(): ...")])
    await loop.chat_session("c1")
    from shared.sessions import transition
    assert transition("c1", "running", {"done"})

    await loop.chat_session("c1", "and in Python?")

    assert get_session("c1").title == "Closures" and len(requests) == 3 and len(titled("c1")) == 1


def test_clean_title():
    assert loop.clean_title('"Closures in JavaScript."\nsecond line') == "Closures in JavaScript"
    assert loop.clean_title("Title: Fix the bulk discount") == "Fix the bulk discount"
    assert loop.clean_title("   ") is None
    assert len(loop.clean_title("word " * 40)) <= 60


def test_renaming_through_the_api_marks_the_title_as_the_users(client, env):
    from tests.fakes import signup
    signup(client)
    sid = client.post("/sessions", json={"message": "hi"}).json()["id"]
    assert get_session(sid).title_source == "auto"
    assert client.patch(f"/sessions/{sid}", json={"title": "Mine"}).status_code == 200
    assert (get_session(sid).title, get_session(sid).title_source) == ("Mine", "user")
