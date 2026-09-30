"""Chats: plain ones without a repo, attaching a repo later, titles and the chat list."""
import asyncio

import pytest

from brain import worker
from shared.bus import SESSIONS_QUEUE
from shared.db import get_db
from shared.events import load_events
from shared.models import User
from shared.sessions import get_session, set_status
from tests.fakes import FakeChannel, FakeConnection, connect_github, llm_final, signup
from tests.test_brain_chat import fake_llm

REPO, OTHER = "Taufik041/otto_test", "some-org/api"


@pytest.fixture
def client(client, fake_github):
    """Signed in, with two installations: 555 sees REPO, 777 sees OTHER."""
    client.user_id = signup(client)["id"]
    connect_github(fake_github, client.user_id, 555, [REPO])
    connect_github(fake_github, client.user_id, 777, [OTHER], account="some-org")
    return client


def jobs(ch):
    return [body for key, body in ch.default_exchange.published if key == SESSIONS_QUEUE]


def run_worker(ch, job):
    """Let a brain worker take one job the gateway published."""
    q = FakeChannel().queue(SESSIONS_QUEUE)
    q.put(job)
    q.close()
    asyncio.run(asyncio.wait_for(worker.consume(FakeConnection(ch), q, 1), 5))


def chat(client, message="what is a closure?"):
    r = client.post("/sessions", json={"message": message})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- plain chats ------------------------------------------------------------------------

def test_a_plain_chat_never_creates_a_sandbox_and_its_reply_is_stored(client, env, monkeypatch):
    ch, orch, _ = env
    r = client.post("/sessions", json={"message": "what is a closure?"})

    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json() == {"id": sid, "status": "queued", "title": "what is a closure?", "repo": None}
    assert jobs(ch) == [{"type": "chat", "session_id": sid}]
    fake_llm(monkeypatch, [llm_final("A function that remembers where it was made.")])

    run_worker(ch, jobs(ch)[0])

    assert orch.calls == []
    assert get_session(sid).status == "done"
    replies = [e["payload"]["message"] for e in client.get(f"/sessions/{sid}/events").json()
               if e["type"] == "llm.message" and e["payload"]["message"]["role"] == "assistant"]
    assert replies == [{"role": "assistant", "content": "A function that remembers where it was made."}]


def test_a_plain_chat_follow_up_is_a_chat_job(client, env):
    ch, orch, _ = env
    sid = chat(client)
    set_status(sid, "done")

    r = client.post(f"/sessions/{sid}/messages", json={"text": "and in Python?"})

    assert r.status_code == 202 and r.json()["repo"] is None
    assert jobs(ch)[-1] == {"type": "chat", "session_id": sid, "text": "and in Python?"}
    assert orch.calls == []


def test_a_plain_chat_has_no_sandbox_to_ask_about_or_stop(client, env):
    ch, orch, _ = env
    sid = chat(client)
    assert client.get(f"/sessions/{sid}").json()["sandbox_status"] is None
    assert client.post(f"/sessions/{sid}/stop").status_code == 200
    assert orch.calls == [] and get_session(sid).status == "stopped"


# --- repos --------------------------------------------------------------------------------

def test_a_chat_with_a_repo_uses_that_repos_installation(client, env):
    ch, orch, _ = env
    r = client.post("/sessions", json={"message": "fix it", "repo": "@some-org/API"})
    sid = r.json()["id"]
    assert r.status_code == 201 and r.json()["repo"] == OTHER  # GitHub's spelling
    assert orch.calls == [("create", sid, f"https://github.com/{OTHER}", 777)]
    assert jobs(ch) == [{"type": "start", "session_id": sid}]


def test_a_repo_the_user_cant_reach_is_403(client, env):
    ch, orch, _ = env
    r = client.post("/sessions", json={"message": "fix it", "repo": "Taufik041/not-connected"})
    assert r.status_code == 403
    assert orch.calls == [] and jobs(ch) == [] and client.get("/sessions").json() == []


def test_attaching_a_repo_later_creates_the_sandbox_on_its_installation(client, env, monkeypatch):
    ch, orch, _ = env
    sid = chat(client, "explain the pricing module")
    fake_llm(monkeypatch, [llm_final("Mention a repo with @ and I'll look.")])
    run_worker(ch, jobs(ch)[0])

    r = client.post(f"/sessions/{sid}/messages", json={"text": "fix the failing tests", "repo": OTHER})

    assert r.status_code == 202 and r.json()["repo"] == OTHER
    assert orch.calls == [("create", sid, f"https://github.com/{OTHER}", 777)]
    assert jobs(ch)[-1] == {"type": "resume", "session_id": sid, "text": "fix the failing tests"}
    row = get_session(sid)
    assert (row.repo, row.status) == (OTHER, "queued")
    assert "repo.attached" in [e.type for e in load_events(sid)]
    assert client.get("/sessions").json()[0]["repo"] == OTHER


def test_a_different_repo_than_the_chats_is_409(client, env):
    ch, orch, _ = env
    sid = client.post("/sessions", json={"message": "fix it", "repo": REPO}).json()["id"]
    set_status(sid, "done")
    orch.calls.clear()

    r = client.post(f"/sessions/{sid}/messages", json={"text": "now this one", "repo": OTHER})

    assert r.status_code == 409 and r.json()["detail"] == "Start a new chat for a different repo."
    assert orch.calls == [] and get_session(sid).status == "done"


def test_naming_the_chats_own_repo_again_is_fine(client, env):
    sid = client.post("/sessions", json={"message": "fix it", "repo": REPO}).json()["id"]
    set_status(sid, "done")
    assert client.post(f"/sessions/{sid}/messages", json={"text": "more", "repo": "taufik041/OTTO_TEST"}
                       ).status_code == 202


def test_attaching_a_repo_the_user_cant_reach_is_403(client, env):
    ch, orch, _ = env
    sid = chat(client)
    set_status(sid, "done")
    r = client.post(f"/sessions/{sid}/messages", json={"text": "fix", "repo": "stranger/repo"})
    assert r.status_code == 403
    assert get_session(sid).repo is None and get_session(sid).status == "done" and orch.calls == []


# --- titles, the list, models ------------------------------------------------------------------

def test_the_title_is_the_first_message_trimmed_to_60(client, env):
    sid = chat(client, "  please   explain\nhow the pricing module works " + "in detail " * 10)
    title = client.get("/sessions").json()[0]["title"]
    assert title == "please explain how the pricing module works in detail in det"
    assert len(title) == 60 and get_session(sid).task.startswith("  please")


def test_renaming_a_chat(client, env):
    older = chat(client, "first")
    sid = chat(client, "second")
    set_status(older, "done")  # activity: older is now the most recent

    r = client.patch(f"/sessions/{sid}", json={"title": "  Fix   pricing tests "})

    assert r.status_code == 200 and r.json()["title"] == "Fix pricing tests"
    listed = client.get("/sessions").json()
    assert [s["id"] for s in listed] == [older, sid]  # renaming isn't activity
    assert client.patch(f"/sessions/{sid}", json={"title": "   "}).status_code == 422
    assert client.patch(f"/sessions/{sid}", json={"title": "x" * 201}).status_code == 422


def test_chats_are_listed_most_recently_active_first(client, env):
    a, b = chat(client, "a"), chat(client, "b")
    assert [s["id"] for s in client.get("/sessions").json()] == [b, a]
    set_status(a, "done")
    client.post(f"/sessions/{a}/messages", json={"text": "more"})
    assert [s["id"] for s in client.get("/sessions").json()] == [a, b]


def test_a_new_chat_uses_the_users_default_model(client, env, monkeypatch):
    from tests.fakes import use_env

    use_env(monkeypatch, {"OPENROUTER_API_KEY": "k", "OPENAI_API_KEY": "k2", "OTTO_OPENAI_MODELS": "model-a"})
    with get_db() as s:
        u = s.get(User, client.user_id)
        u.default_model = "openai:model-a"
        s.add(u)
    assert get_session(chat(client)).model == "openai:model-a"
    r = client.post("/sessions", json={"message": "x", "model": "openrouter:openrouter/free"})
    assert get_session(r.json()["id"]).model == "openrouter:openrouter/free"  # asking wins
