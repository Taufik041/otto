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
    # a plain chat's job carries the live facts its prompt tells the model (tests/test_prompts.py)
    facts = {"workers": "online", "repos": ["Taufik041/otto_test", "some-org/api"]}
    assert jobs(ch) == [{"type": "chat", "session_id": sid, "facts": facts}]
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
    assert jobs(ch)[-1] == {"type": "chat", "session_id": sid, "text": "and in Python?",
                            "facts": {"workers": "online", "repos": ["Taufik041/otto_test", "some-org/api"]}}
    assert orch.calls == []


def test_a_plain_chat_job_says_when_the_workers_are_offline(client, env):
    ch, orch, _ = env
    orch.online = False
    r = client.post("/sessions", json={"message": "why are the workers offline?"})
    assert r.status_code == 201
    assert jobs(ch)[-1]["facts"]["workers"] == "offline"


def test_a_plain_chat_job_leaves_the_repos_out_when_github_cant_say(client, env, monkeypatch):
    from gateway import github_app

    def broken(user_id):
        raise github_app.GitHubError("GitHub is down")

    monkeypatch.setattr(github_app, "user_repos", broken)
    ch, _, _ = env
    client.post("/sessions", json={"message": "hi"})
    assert jobs(ch)[-1]["facts"] == {"workers": "online"}


def test_an_agent_job_carries_no_facts(client, env):
    ch, _, _ = env
    client.post("/sessions", json={"message": "fix it", "repo": "@Taufik041/otto_test"})
    assert "facts" not in jobs(ch)[-1]


def test_a_plain_chat_has_no_sandbox_to_ask_about_or_stop(client, env):
    _ch, orch, _ = env
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
    _ch, orch, _ = env
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
    _ch, orch, _ = env
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


# --- a follow-up is stored the moment it's sent ---------------------------------------------

def user_messages(sid):
    return [e for e in load_events(sid) if e.type == "llm.message" and e.payload["message"]["role"] == "user"]


def test_a_follow_up_is_an_event_as_soon_as_it_is_posted_and_the_worker_does_not_repeat_it(client, env, monkeypatch):
    from brain.resume import rebuild_messages

    ch, _, _ = env
    sid = chat(client)
    fake_llm(monkeypatch, [llm_final("A function with its scope."), llm_final("Closures"), llm_final("def f(): ...")])
    run_worker(ch, jobs(ch)[0])

    r = client.post(f"/sessions/{sid}/messages", json={"text": "and in Python?"})

    assert r.status_code == 202
    # visible right away (before any worker): the client reads it from the events, live or not
    [follow] = [e for e in user_messages(sid) if e.payload["message"]["content"] == "and in Python?"]
    assert follow.payload == {"message": {"role": "user", "content": "and in Python?"}}
    assert client.get(f"/sessions/{sid}/events", params={"after_seq": follow.seq - 1}).json()[0]["seq"] == follow.seq

    run_worker(ch, jobs(ch)[-1])

    assert [e.payload["message"]["content"] for e in user_messages(sid)] == ["what is a closure?", "and in Python?"]
    conversation = rebuild_messages(load_events(sid))
    assert [m["content"] for m in conversation if m["role"] == "user"] == ["what is a closure?", "and in Python?"]
    assert conversation[-1] == {"role": "assistant", "content": "def f(): ..."}


def test_a_follow_up_that_attaches_a_repo_is_stored_after_the_attachment(client, env):
    _ch, _, _ = env
    sid = chat(client)
    set_status(sid, "done")

    assert client.post(f"/sessions/{sid}/messages", json={"text": "fix it", "repo": REPO}).status_code == 202

    types = [(e.type, e.payload) for e in load_events(sid) if e.type in ("repo.attached", "llm.message")]
    assert types[-2:] == [("repo.attached", {"repo": REPO}), ("llm.message", {"message": {"role": "user", "content": "fix it"}})]


def test_a_refused_follow_up_is_not_stored(client, env):
    sid = chat(client)  # still queued: busy
    assert client.post(f"/sessions/{sid}/messages", json={"text": "more"}).status_code == 409
    assert not [e for e in user_messages(sid) if e.payload["message"]["content"] == "more"]


# --- client_message_id: a follow-up is stored once, however often it's posted ---------------

def user_payloads(sid) -> list[dict]:
    return [e.payload for e in load_events(sid)
            if e.type == "llm.message" and e.payload["message"]["role"] == "user"]


def test_a_follow_ups_event_carries_its_client_message_id(client, env):
    sid = chat(client)
    set_status(sid, "done")
    r = client.post(f"/sessions/{sid}/messages", json={"text": "and in Python?", "client_message_id": "m-0123456789"})  # gitleaks:allow  # gitleaks:allow
    assert r.status_code == 202
    assert user_payloads(sid)[-1] == {"message": {"role": "user", "content": "and in Python?"},
                                      "client_message_id": "m-0123456789"}  # gitleaks:allow  # gitleaks:allow


@pytest.mark.parametrize("meanwhile", ["queued", "running", "done"])
def test_posting_the_same_client_message_id_again_stores_and_queues_nothing(client, env, meanwhile):
    """A retry or a double click: whatever the chat is doing by then, the second post is a no-op."""
    ch, _, _ = env
    sid = chat(client)
    set_status(sid, "done")
    body = {"text": "and in Python?", "client_message_id": "m-0123456789"}  # gitleaks:allow  # gitleaks:allow
    assert client.post(f"/sessions/{sid}/messages", json=body).status_code == 202
    set_status(sid, meanwhile)
    before = len(jobs(ch))

    r = client.post(f"/sessions/{sid}/messages", json=body)

    assert r.status_code == 202 and r.json() == {"id": sid, "status": meanwhile, "repo": None}
    assert [m["message"]["content"] for m in user_payloads(sid)].count("and in Python?") == 1
    assert len(jobs(ch)) == before


def test_another_client_message_id_is_another_message(client, env):
    sid = chat(client)
    set_status(sid, "done")
    client.post(f"/sessions/{sid}/messages", json={"text": "again", "client_message_id": "m-aaaaaaaa"})
    set_status(sid, "done")
    assert client.post(f"/sessions/{sid}/messages", json={"text": "again", "client_message_id": "m-bbbbbbbb"}).status_code == 202
    assert [m.get("client_message_id") for m in user_payloads(sid)][-2:] == ["m-aaaaaaaa", "m-bbbbbbbb"]


def test_the_same_client_message_id_in_another_chat_is_its_own(client, env):
    a, b = chat(client), chat(client, "another")
    for sid in (a, b):
        set_status(sid, "done")
        r = client.post(f"/sessions/{sid}/messages", json={"text": "hi", "client_message_id": "m-0123456789"})  # gitleaks:allow  # gitleaks:allow
        assert r.status_code == 202
        assert user_payloads(sid)[-1]["client_message_id"] == "m-0123456789"


@pytest.mark.parametrize("bad", ["short", "x" * 65, "has spaces in it", "../../etc"])
def test_a_malformed_client_message_id_is_422(client, env, bad):
    sid = chat(client)
    set_status(sid, "done")
    assert client.post(f"/sessions/{sid}/messages", json={"text": "hi", "client_message_id": bad}).status_code == 422


def test_without_a_client_message_id_a_follow_up_still_works(client, env):
    sid = chat(client)
    set_status(sid, "done")
    assert client.post(f"/sessions/{sid}/messages", json={"text": "hi"}).status_code == 202
    assert "client_message_id" not in user_payloads(sid)[-1]


def test_the_store_itself_never_keeps_a_client_message_id_twice():
    from shared.events import append_event
    from shared.sessions import create_session

    create_session("c1", task="t", repo=None, model="openrouter:openrouter/free")
    msg = {"message": {"role": "user", "content": "hi"}, "client_message_id": "m-0123456789"}  # gitleaks:allow  # gitleaks:allow
    first = append_event("c1", "llm.message", msg, client_message_id="m-0123456789")  # gitleaks:allow  # gitleaks:allow
    again = append_event("c1", "llm.message", msg, client_message_id="m-0123456789")  # gitleaks:allow  # gitleaks:allow
    assert again == first and len(user_payloads("c1")) == 1


# --- client_message_id on a new chat: the first message makes one chat, however often it's posted

def test_posting_a_new_chat_again_with_the_same_client_message_id_returns_the_first(client, env):
    """A retry or a double click: the second post answers with the chat the first one made."""
    ch, _, _ = env
    body = {"message": "what is a closure?", "client_message_id": "m-0123456789"}  # gitleaks:allow
    first = client.post("/sessions", json=body)
    assert first.status_code == 201

    again = client.post("/sessions", json=body)

    assert again.status_code == 200
    assert again.json() == first.json() | {"status": get_session(first.json()["id"]).status}
    assert [s["id"] for s in client.get("/sessions").json()] == [first.json()["id"]]
    assert len(jobs(ch)) == 1


def test_a_repo_chat_posted_again_creates_no_second_sandbox(client, env):
    _, orch, _ = env
    body = {"message": "fix it", "repo": REPO, "client_message_id": "m-0123456789"}  # gitleaks:allow
    sid = client.post("/sessions", json=body).json()["id"]

    r = client.post("/sessions", json=body)

    assert r.status_code == 200 and r.json()["id"] == sid and r.json()["repo"] == REPO
    assert [c for c in orch.calls if c[0] == "create"] == [("create", sid, f"https://github.com/{REPO}", 555)]


def test_a_new_chat_posted_again_counts_once_against_the_limit(client, env, monkeypatch):
    from shared import config

    monkeypatch.setattr(config, "MAX_ACTIVE_SESSIONS", 1)
    body = {"message": "hi", "client_message_id": "m-0123456789"}  # gitleaks:allow
    assert client.post("/sessions", json=body).status_code == 201
    assert client.post("/sessions", json=body).status_code == 200  # not 429: it's the same chat


def test_another_client_message_id_is_another_chat(client, env):
    a = client.post("/sessions", json={"message": "hi", "client_message_id": "m-aaaaaaaa"}).json()["id"]
    b = client.post("/sessions", json={"message": "hi", "client_message_id": "m-bbbbbbbb"}).json()["id"]
    assert a != b


def test_without_a_client_message_id_every_post_is_a_new_chat(client, env):
    assert chat(client, "hi") != chat(client, "hi")


def test_another_users_client_message_id_is_their_own(client, env):
    from tests.fakes import log_in_as

    body = {"message": "hi", "client_message_id": "m-0123456789"}  # gitleaks:allow
    mine = client.post("/sessions", json=body).json()["id"]
    log_in_as(client, signup(client, email="someone@example.com", name="Someone")["id"])

    theirs = client.post("/sessions", json=body)

    assert theirs.status_code == 201 and theirs.json()["id"] != mine


@pytest.mark.parametrize("bad", ["short", "x" * 65, "has spaces in it", "../../etc"])
def test_a_malformed_client_message_id_on_a_new_chat_is_422(client, env, bad):
    assert client.post("/sessions", json={"message": "hi", "client_message_id": bad}).status_code == 422


def test_the_store_never_keeps_one_users_client_message_id_on_two_chats(client):
    """Two gateways racing past the lookup: the database refuses the second chat."""
    import sqlalchemy as sa

    from shared.sessions import create_session

    cid = "m-0123456789"  # gitleaks:allow
    create_session("c1", task="t", repo=None, model="m", user_id=client.user_id, client_message_id=cid)
    with pytest.raises(sa.exc.IntegrityError):
        create_session("c2", task="t", repo=None, model="m", user_id=client.user_id, client_message_id=cid)
