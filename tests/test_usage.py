"""Token usage: recorded per LLM call, the daily limit, GET /usage, and stopping sandboxes."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from brain import loop
from shared import config, usage
from shared.bus import SESSIONS_QUEUE, actions_queue, results_queue
from shared.db import get_db
from shared.events import load_events
from shared.models import Usage, User
from shared.sessions import create_session, get_session, set_status
from tests.fakes import (FakeChannel, auto_reply, connect_github, llm_final, llm_tool_calls, make_user,
                         signup)
from tests.test_brain_chat import fake_llm

REPO = "Taufik041/otto_test"
NOW = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)


def rows() -> list[Usage]:
    with get_db() as s:
        return list(s.exec(select(Usage).order_by(Usage.id)).all())


def spend(user_id, sid, tokens, when=None, model="openrouter:openrouter/free", prompt=None):
    """A usage row: `tokens` in total (prompt, unless given, is half). sid None: a session of its own."""
    prompt = tokens // 2 if prompt is None else prompt
    if sid is None:
        sid = f"spent-{user_id}"
        if get_session(sid) is None:
            create_session(sid, task="t", repo=None, model=model, status="done", user_id=user_id)
    with get_db() as s:
        s.add(Usage(user_id=user_id, session_id=sid, provider=model.split(":")[0], model=model,
                    prompt_tokens=prompt, completion_tokens=tokens - prompt, created_at=when or usage.utcnow()))


def set_limit(user_id, limit):
    with get_db() as s:
        u = s.get(User, user_id)
        u.daily_token_limit = limit
        s.add(u)


def used(prompt, completion):
    from types import SimpleNamespace as NS
    return NS(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)


def agent(sid="s1", user_id="u1", status="running", repo=REPO):
    create_session(sid, task="fix it", repo=repo, model="openrouter:openrouter/free", status=status, user_id=user_id)
    ch = FakeChannel()
    results = ch.queue(results_queue(sid))
    auto_reply(ch, results)
    return ch, results


# --- recording --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_each_llm_call_is_recorded_with_its_tokens(monkeypatch):
    make_user("u1")
    ch, results = agent()
    fake_llm(monkeypatch, [llm_tool_calls(("git_status", {}), usage=used(120, 30)),
                           llm_final("done")])  # no usage in the response: counted as 0

    await asyncio.wait_for(loop.start_session(ch, results, "s1", "fix it"), 2)

    assert [(r.user_id, r.session_id, r.provider, r.model, r.prompt_tokens, r.completion_tokens) for r in rows()] == [
        ("u1", "s1", "openrouter", "openrouter:openrouter/free", 120, 30),
        ("u1", "s1", "openrouter", "openrouter:openrouter/free", 0, 0)]
    events = [e.payload for e in load_events("s1") if e.type == "llm.usage"]
    assert events[0] == {"provider": "openrouter", "model": "openrouter:openrouter/free",
                         "prompt_tokens": 120, "completion_tokens": 30}
    assert len(events) == 2


@pytest.mark.asyncio
async def test_chat_calls_are_recorded_too(monkeypatch):
    make_user("u1")
    create_session("c1", task="hi", repo=None, model="openrouter:openrouter/free", status="running", user_id="u1")
    fake_llm(monkeypatch, [llm_final("hello", usage=used(10, 5))])
    await loop.chat_session("c1")
    assert [(r.prompt_tokens, r.completion_tokens) for r in rows()] == [(10, 5)]


@pytest.mark.asyncio
async def test_sessions_without_an_owner_are_recorded_but_never_limited(monkeypatch):
    ch, results = agent(user_id=None)
    fake_llm(monkeypatch, [llm_final("done", usage=used(10**9, 1))])
    await loop.start_session(ch, results, "s1", "fix it")
    [row] = rows()
    assert row.user_id is None and get_session("s1").status == "done"


# --- the daily limit in the brain ---------------------------------------------------------

@pytest.mark.asyncio
async def test_at_the_limit_the_session_stops_cleanly_as_limited(monkeypatch):
    make_user("u1", daily_token_limit=100)
    spend("u1", None, 100)
    ch, results = agent()
    requests = fake_llm(monkeypatch, [])

    await asyncio.wait_for(loop.start_session(ch, results, "s1", "fix it"), 2)

    assert requests == []  # no LLM call at all
    assert get_session("s1").status == "limited"
    [ev] = [e.payload for e in load_events("s1") if e.type == "usage.limit_reached"]
    assert (ev["used"], ev["limit"]) == (100, 100)
    tomorrow = (usage.utcnow() + timedelta(days=1)).date().isoformat()
    assert ev["resets_at"] == f"{tomorrow}T00:00:00+00:00"
    assert ch.default_exchange.published == []  # the sandbox isn't touched: it stays warm


@pytest.mark.asyncio
async def test_crossing_the_limit_mid_session_stops_before_the_next_call(monkeypatch):
    make_user("u1", daily_token_limit=100)
    ch, results = agent()
    requests = fake_llm(monkeypatch, [llm_tool_calls(("git_status", {}), usage=used(90, 20)),
                                      llm_final("never asked")])

    await asyncio.wait_for(loop.start_session(ch, results, "s1", "fix it"), 2)

    assert len(requests) == 1
    assert get_session("s1").status == "limited"
    msgs = [e.payload["message"] for e in load_events("s1") if e.type == "llm.message"]
    assert msgs[-1]["role"] == "tool"  # the call's result was stored: the session can resume later
    assert [e.payload["used"] for e in load_events("s1") if e.type == "usage.limit_reached"] == [110]


@pytest.mark.asyncio
async def test_a_chat_at_the_limit_is_limited(monkeypatch):
    make_user("u1", daily_token_limit=100)
    spend("u1", None, 150)
    create_session("c1", task="hi", repo=None, model="openrouter:openrouter/free", status="running", user_id="u1")
    requests = fake_llm(monkeypatch, [])
    await loop.chat_session("c1")
    assert requests == [] and get_session("c1").status == "limited"


def test_yesterdays_tokens_dont_count():
    make_user("u1", daily_token_limit=100)
    midnight = NOW.replace(hour=0)
    spend("u1", None, 500, when=midnight - timedelta(seconds=1))
    spend("u1", None, 40, when=midnight)
    assert usage.used_today("u1", now=NOW) == 40
    assert usage.limit_status("u1", now=NOW) is None
    spend("u1", None, 60, when=NOW)
    assert usage.limit_status("u1", now=NOW) == {"used": 100, "limit": 100,
                                                 "resets_at": "2026-10-01T00:00:00+00:00"}


# --- prices ---------------------------------------------------------------------------------

def test_model_prices_from_the_env():
    assert config.model_prices({}) == {}
    assert config.model_prices({"MODEL_PRICES": '{"openai:gpt-x": {"input_per_1m": 0.15, "output_per_1m": 0.6}}'}) \
        == {"openai:gpt-x": {"input_per_1m": 0.15, "output_per_1m": 0.6}}
    assert config.model_prices({"MODEL_PRICES": '{"m": {"input_per_1m": 1}}'}) == \
        {"m": {"input_per_1m": 1.0, "output_per_1m": 0.0}}


@pytest.mark.parametrize("raw", ["not json", "[]", '{"m": 3}', '{"m": {"input_per_1m": "cheap"}}',
                                 '{"m": {"input_per_1m": -1}}'])
def test_bad_model_prices_are_refused(raw):
    with pytest.raises(ValueError, match="MODEL_PRICES"):
        config.model_prices({"MODEL_PRICES": raw})


def test_cost(monkeypatch):
    monkeypatch.setattr(config, "MODEL_PRICES", {"openai:gpt-x": {"input_per_1m": 2.0, "output_per_1m": 8.0}})
    assert usage.cost("openai:gpt-x", 1_000_000, 500_000) == pytest.approx(6.0)
    assert usage.cost("openrouter:openrouter/free", 10**9, 10**9) == 0  # no price: free


# --- the gateway ------------------------------------------------------------------------------

@pytest.fixture
def me(client, fake_github):
    user_id = signup(client)["id"]
    connect_github(fake_github, user_id, 555, [REPO])
    return user_id


def test_new_chats_and_follow_ups_are_429_over_the_limit(client, env, me):
    ch, orch, _ = env
    done = client.post("/sessions", json={"message": "hi"}).json()["id"]
    set_status(done, "done")
    set_limit(me, 100)
    spend(me, done, 100)
    published = len(ch.default_exchange.published)

    for r in (client.post("/sessions", json={"message": "again", "repo": REPO}),
              client.post(f"/sessions/{done}/messages", json={"text": "more"})):
        assert r.status_code == 429
        body = r.json()
        assert body["code"] == "daily_limit" and body["resets_at"].endswith("T00:00:00+00:00")
        assert (body["used"], body["limit"]) == (100, 100)
    assert len(ch.default_exchange.published) == published and orch.calls == []
    assert get_session(done).status == "done"


def test_a_limited_session_takes_a_follow_up_once_under_the_limit(client, env, me):
    sid = client.post("/sessions", json={"message": "hi"}).json()["id"]
    set_status(sid, "limited")
    assert client.post(f"/sessions/{sid}/messages", json={"text": "go on"}).status_code == 202


def test_get_usage(client, env, me, monkeypatch):
    ch, orch, _ = env
    monkeypatch.setattr(config, "MODEL_PRICES", {"openai:gpt-x": {"input_per_1m": 2.0, "output_per_1m": 8.0}})
    monkeypatch.setattr(usage, "utcnow", lambda: NOW)
    a = client.post("/sessions", json={"message": "a", "repo": REPO}).json()["id"]
    b = client.post("/sessions", json={"message": "b"}).json()["id"]
    spend(me, a, 1000, when=NOW)
    spend(me, b, 400, when=NOW - timedelta(hours=10), model="openai:gpt-x", prompt=300)
    spend(me, a, 2000, when=NOW - timedelta(days=3))
    spend(me, a, 7000, when=NOW - timedelta(days=20))   # last month and > 14 days ago
    other = make_user("other")
    spend(other.id, None, 99999, when=NOW)               # not mine

    r = client.get("/usage").json()

    assert r["today"] == {"tokens": 1400, "limit": 50000, "resets_at": "2026-10-01T00:00:00+00:00"}
    # September: a, b and the 20-days-ago row are all this month
    assert r["month"]["tokens"] == 10400 and r["month"]["sessions"] == 2
    assert r["month"]["est_cost_usd"] == pytest.approx(300 * 2 / 1e6 + 100 * 8 / 1e6)
    assert len(r["daily"]) == 14
    assert r["daily"][0]["date"] == "2026-09-17" and r["daily"][-1] == {"date": "2026-09-30", "tokens": 1400}
    assert {d["date"]: d["tokens"] for d in r["daily"]}["2026-09-27"] == 2000
    assert sum(d["tokens"] for d in r["daily"]) == 3400
    assert r["by_model"] == [
        {"model": "openrouter:openrouter/free", "tokens": 10000, "est_cost_usd": 0.0},
        {"model": "openai:gpt-x", "tokens": 400, "est_cost_usd": pytest.approx(0.0014)}]
    assert r["active_sandboxes"] == [{"session_id": a, "title": "a", "repo": REPO, "sandbox_status": "running"}]


def test_usage_lists_only_live_sandboxes(client, env, me):
    ch, orch, _ = env
    a = client.post("/sessions", json={"message": "a", "repo": REPO}).json()["id"]
    b = client.post("/sessions", json={"message": "b", "repo": REPO}).json()["id"]
    orch.status[b] = "finished"
    assert [s["session_id"] for s in client.get("/usage").json()["active_sandboxes"]] == [a]


def test_usage_needs_a_login(client):
    assert client.get("/usage").status_code == 401


# --- stopping one sandbox --------------------------------------------------------------------------

def test_stopping_a_sandbox_of_a_finished_session(client, env, me):
    ch, orch, runners = env
    sid = client.post("/sessions", json={"message": "a", "repo": REPO}).json()["id"]
    set_status(sid, "done")
    runners.alive.add(sid)

    r = client.post(f"/sessions/{sid}/sandbox/stop")

    assert r.status_code == 200 and r.json() == {"id": sid, "status": "done", "sandbox_status": "missing"}
    assert ("destroy", sid) in orch.calls
    assert ch.queues[actions_queue(sid)].deleted == (False, False)
    assert get_session(sid).status == "done"  # a follow-up will start a new sandbox


def test_stopping_the_sandbox_of_a_running_session_stops_it(client, env, me):
    ch, orch, _ = env
    sid = client.post("/sessions", json={"message": "a", "repo": REPO}).json()["id"]
    assert client.post(f"/sessions/{sid}/sandbox/stop").json()["status"] == "stopped"
    assert get_session(sid).status == "stopped"


def test_stopping_someone_elses_sandbox_is_404(client, env, me):
    ch, orch, _ = env
    create_session("theirs0001", task="t", repo=REPO, model="m", user_id=make_user("u2").id)
    assert client.post("/sessions/theirs0001/sandbox/stop").status_code == 404
    assert orch.calls == []
