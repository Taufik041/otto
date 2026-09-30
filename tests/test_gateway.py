import asyncio, json, time
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from orchestrator import sandbox
from shared import config
from shared.bus import SESSIONS_QUEUE, actions_queue, make_result, results_queue
from shared.db import get_db
from shared.events import append_event, load_events
from shared import usage
from shared.models import Session, SessionEvent, Usage, utcnow
from shared.sessions import create_session, get_session, set_status
from gateway import app as gateway_app, live
from tests.conftest import ORIGIN
from tests.fakes import FakeChannel, connect_github, make_user, signup, use_env

REPO = "Taufik041/otto_test"
REPO_URL = "https://github.com/Taufik041/otto_test"
INST = 555


@pytest.fixture
def client(client, fake_github):
    """Every test here acts as one signed-in user, client.user_id, whose installation INST can
    see REPO."""
    client.user_id = signup(client)["id"]
    connect_github(fake_github, client.user_id, INST, [REPO])
    return client


def jobs(ch):
    return [body for key, body in ch.default_exchange.published if key == SESSIONS_QUEUE]


def actions(ch, sid):
    return [body["kind"] for key, body in ch.default_exchange.published if key == actions_queue(sid)]


def types(sid):
    return [e.type for e in load_events(sid)]


# --- POST /sessions --------------------------------------------------------------

def test_create_session(client, env):
    ch, orch, _ = env
    r = client.post("/sessions", json={"repo": REPO, "message": "fix the tests"})

    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json() == {"id": sid, "status": "queued", "title": "fix the tests", "repo": REPO}
    assert len(sid) == 10 and sid.isalnum() and sid == sid.lower()
    row = get_session(sid)
    assert (row.status, row.repo, row.task, row.user_id) == ("queued", REPO, "fix the tests", client.user_id)
    assert orch.calls == [("create", sid, REPO_URL, INST)]
    assert jobs(ch) == [{"type": "start", "session_id": sid}]
    assert types(sid) == ["session.created", "session.status"]


def test_ids_are_unique(client):
    ids = {client.post("/sessions", json={"repo": REPO, "message": "t"}).json()["id"] for _ in range(3)}
    assert len(ids) == 3


def test_create_sandbox_failure_is_502_and_failed(client, env):
    ch, orch, _ = env
    orch.fail_create = RuntimeError("k8s says no; token ghs_abcdef123")

    r = client.post("/sessions", json={"repo": REPO, "message": "t"})

    assert r.status_code == 502
    assert "ghs_" not in r.text
    [row] = [get_session(s["id"]) for s in client.get("/sessions").json()]
    assert row.status == "failed"
    err = [e for e in load_events(row.id) if e.type == "error"]
    assert err and "k8s says no" in err[0].payload["message"] and "ghs_" not in json.dumps(err[0].payload)
    assert jobs(ch) == []


def test_too_many_active_agent_sessions_is_429_per_user(client, env, monkeypatch):
    monkeypatch.setattr(config, "MAX_ACTIVE_SESSIONS", 2)
    monkeypatch.setattr(config, "MAX_ACTIVE_SANDBOXES", 10)
    create_session("old1", task="t", repo=REPO, model="m", status="done", user_id=client.user_id)  # not active
    create_session("theirs0001", task="t", repo=REPO, model="m", status="running", user_id=make_user("u2").id)
    assert client.post("/sessions", json={"repo": REPO, "message": "a"}).status_code == 201
    assert client.post("/sessions", json={"repo": REPO, "message": "b"}).status_code == 201

    r = client.post("/sessions", json={"repo": REPO, "message": "c"})

    assert r.status_code == 429 and "2 agent sessions" in r.json()["detail"]
    assert len(env[1].calls) == 2
    # plain chats neither count nor are capped
    for _ in range(3):
        assert client.post("/sessions", json={"message": "hi"}).status_code == 201


def test_the_cluster_wide_sandbox_cap_is_429(client, env, monkeypatch):
    monkeypatch.setattr(config, "MAX_ACTIVE_SESSIONS", 10)
    monkeypatch.setattr(config, "MAX_ACTIVE_SANDBOXES", 2)
    create_session("theirs0001", task="t", repo=REPO, model="m", status="running", user_id=make_user("u2").id)
    create_session("chat000001", task="t", repo=None, model="m", status="running", user_id="u2")  # no sandbox
    assert client.post("/sessions", json={"repo": REPO, "message": "a"}).status_code == 201

    r = client.post("/sessions", json={"repo": REPO, "message": "b"})

    assert r.status_code == 429 and "sandboxes" in r.json()["detail"]
    assert len(env[1].calls) == 1
    assert client.post("/sessions", json={"message": "hi"}).status_code == 201


def test_the_caps_apply_to_follow_ups_that_need_a_sandbox(client, env, monkeypatch):
    ch, orch, _ = env
    monkeypatch.setattr(config, "MAX_ACTIVE_SESSIONS", 1)
    chat_id = client.post("/sessions", json={"message": "hi"}).json()["id"]
    agent = finished_session(client.user_id)
    set_status(chat_id, "done")
    assert client.post("/sessions", json={"repo": REPO, "message": "busy"}).status_code == 201
    orch.calls.clear()

    for sid, body in [(chat_id, {"text": "now fix it", "repo": REPO}), (agent, {"text": "go on"})]:
        r = client.post(f"/sessions/{sid}/messages", json=body)
        assert r.status_code == 429, sid
        assert get_session(sid).status == "done"
    assert get_session(chat_id).repo is None and orch.calls == []
    # a plain chat's follow-up needs no sandbox
    assert client.post(f"/sessions/{chat_id}/messages", json={"text": "just chatting"}).status_code == 202


def test_bad_request_is_422(client, env):
    assert client.post("/sessions", json={"repo": "not a repo", "message": "t"}).status_code == 422
    assert client.post("/sessions", json={"repo": "https://github.com/o/r", "message": "t"}).status_code == 422
    assert client.post("/sessions", json={"repo": REPO, "message": ""}).status_code == 422
    assert env[1].calls == []


# --- models ----------------------------------------------------------------------

BOTH = {"OPENROUTER_API_KEY": "orkey-one", "OPENAI_API_KEY": "oaikey-one", "OTTO_OPENAI_MODELS": "model-a,model-b"}


def test_create_without_a_model_uses_the_default(client):
    sid = client.post("/sessions", json={"repo": REPO, "message": "t"}).json()["id"]
    assert get_session(sid).model == "openrouter:openrouter/free"
    assert load_events(sid)[0].payload["model"] == "openrouter:openrouter/free"


def test_create_with_a_model(client, monkeypatch):
    use_env(monkeypatch, BOTH)
    r = client.post("/sessions", json={"repo": REPO, "message": "t", "model": "openai:model-b"})

    assert r.status_code == 201
    sid = r.json()["id"]
    assert get_session(sid).model == "openai:model-b"
    assert load_events(sid)[0].payload == {"task": "t", "repo": REPO, "model": "openai:model-b"}
    assert client.get(f"/sessions/{sid}").json()["model"] == "openai:model-b"


@pytest.mark.parametrize("model", ["nope", "openai:not-in-catalog", "openai:model-a", "", 3])
def test_unknown_or_unavailable_model_is_422(client, env, monkeypatch, model):
    # no OpenAI key: openai:model-a is in the catalog, but unavailable
    use_env(monkeypatch, {"OPENROUTER_API_KEY": "orkey-one", "OTTO_OPENAI_MODELS": "model-a"})
    r = client.post("/sessions", json={"repo": REPO, "message": "t", "model": model})
    assert r.status_code == 422
    assert env[1].calls == [] and client.get("/sessions").json() == []


def test_no_available_default_is_503(client, env, monkeypatch):
    use_env(monkeypatch, {})
    r = client.post("/sessions", json={"repo": REPO, "message": "t"})
    assert r.status_code == 503 and "OPENROUTER_API_KEY" in r.json()["detail"]
    assert env[1].calls == [] and client.get("/sessions").json() == []


def test_follow_up_keeps_the_sessions_model(client, env, monkeypatch):
    use_env(monkeypatch, BOTH)
    sid = client.post("/sessions", json={"repo": REPO, "message": "t", "model": "openai:model-a"}).json()["id"]
    set_status(sid, "done")
    monkeypatch.setattr(config, "DEFAULT_MODEL", "openrouter:openrouter/free")

    assert client.post(f"/sessions/{sid}/messages", json={"text": "more"}).status_code == 202
    assert get_session(sid).model == "openai:model-a"
    assert jobs(env[0])[-1] == {"type": "resume", "session_id": sid, "text": "more"}  # no model in the job


def test_follow_up_cannot_switch_the_model(client, env, monkeypatch):
    use_env(monkeypatch, BOTH)
    sid = client.post("/sessions", json={"repo": REPO, "message": "t", "model": "openai:model-a"}).json()["id"]
    set_status(sid, "done")

    r = client.post(f"/sessions/{sid}/messages", json={"text": "more", "model": "openrouter:openrouter/free"})

    assert r.status_code == 422 and "fixed" in r.text
    assert get_session(sid).model == "openai:model-a" and get_session(sid).status == "done"


def test_models_reflect_the_keys_present(client, monkeypatch):
    use_env(monkeypatch, {"OPENAI_API_KEY": "oaikey-one", "OTTO_OPENAI_MODELS": "model-a"})
    assert client.get("/models").json() == {
        "default_model": "openai:model-a",
        "models": [
            {"id": "openrouter:openrouter/free", "label": "OpenRouter Free", "provider": "openrouter",
             "available": False},
            {"id": "openai:model-a", "label": "OpenAI model-a", "provider": "openai", "available": True},
        ]}

    use_env(monkeypatch, BOTH)
    r = client.get("/models").json()
    assert r["default_model"] == "openrouter:openrouter/free"
    assert [m["available"] for m in r["models"]] == [True, True, True]
    assert "orkey" not in json.dumps(r) and "oaikey" not in json.dumps(r)


# --- reading ---------------------------------------------------------------------

def test_list_get_and_events(client, env):
    a = client.post("/sessions", json={"repo": REPO, "message": "first"}).json()["id"]
    b = client.post("/sessions", json={"repo": REPO, "message": "second"}).json()["id"]

    listed = client.get("/sessions").json()
    assert [s["id"] for s in listed] == [b, a]
    assert set(listed[0]) == {"id", "title", "status", "repo", "model", "pr_url", "updated_at"}
    assert (listed[0]["title"], listed[0]["repo"]) == ("second", REPO)

    one = client.get(f"/sessions/{a}").json()
    assert one["id"] == a and one["sandbox_status"] == "running"
    assert (one["task"], one["repo_url"]) == ("first", REPO_URL)
    assert one["work_branch"] is None and one["pr_url"] is None
    assert client.get("/sessions/nope").status_code == 404

    evs = client.get(f"/sessions/{a}/events").json()
    assert [e["seq"] for e in evs] == [1, 2] and evs[0]["type"] == "session.created"
    assert [e["seq"] for e in client.get(f"/sessions/{a}/events?after_seq=1").json()] == [2]
    assert client.get("/sessions/nope/events").status_code == 404


# --- follow-ups ------------------------------------------------------------------

def finished_session(user_id, sid="abcdef0123", status="done"):
    create_session(sid, task="t", repo=REPO, model="m", status=status, user_id=user_id)
    return sid


def test_follow_up_reuses_a_warm_sandbox(client, env):
    ch, orch, runners = env
    sid = finished_session(client.user_id)
    orch.status[sid] = "running"
    runners.alive.add(sid)

    r = client.post(f"/sessions/{sid}/messages", json={"text": "also add a test"})

    assert r.status_code == 202 and r.json() == {"id": sid, "status": "queued", "repo": REPO}
    assert orch.calls == []
    assert actions(ch, sid) == ["control.ping"]
    assert "sandbox.reused" in types(sid) and "sandbox.recreated" not in types(sid)
    assert jobs(ch) == [{"type": "resume", "session_id": sid, "text": "also add a test"}]
    assert get_session(sid).status == "queued"


@pytest.mark.parametrize("state", ["running", "finished", "missing"])
def test_follow_up_recreates_a_dead_sandbox(client, env, state):
    ch, orch, _ = env
    sid = finished_session(client.user_id)
    if state != "missing":
        orch.status[sid] = state  # "running" but its runner doesn't answer the ping
    ch.queue(actions_queue(sid)).put({"stale": "action"})

    r = client.post(f"/sessions/{sid}/messages", json={"text": "more"})

    assert r.status_code == 202
    assert actions(ch, sid) == (["control.ping"] if state == "running" else [])
    assert orch.calls == [("remove", sid), ("create", sid, REPO_URL, INST)]
    for q in (actions_queue(sid), results_queue(sid)):
        assert ch.queues[q].purged >= 1
    assert ch.queues[actions_queue(sid)].pending() == 0  # nothing stale left for the new pod
    evs = load_events(sid)
    recreated = [e for e in evs if e.type == "sandbox.recreated"]
    assert recreated and recreated[0].payload == {"previous": state}
    assert jobs(ch) == [{"type": "resume", "session_id": sid, "text": "more"}]


@pytest.mark.parametrize("status", ["provisioning", "queued", "running"])
def test_follow_up_on_a_busy_session_is_409(client, env, status):
    ch, orch, _ = env
    sid = finished_session(client.user_id, status=status)
    r = client.post(f"/sessions/{sid}/messages", json={"text": "more"})
    assert r.status_code == 409
    assert orch.calls == [] and jobs(ch) == [] and actions(ch, sid) == []
    assert get_session(sid).status == status


def test_follow_up_on_missing_session_is_404(client):
    assert client.post("/sessions/nope/messages", json={"text": "x"}).status_code == 404


def test_follow_up_recreate_failure_is_502(client, env):
    ch, orch, _ = env
    sid = finished_session(client.user_id)
    orch.fail_create = RuntimeError("quota")
    r = client.post(f"/sessions/{sid}/messages", json={"text": "more"})
    assert r.status_code == 502
    assert get_session(sid).status == "failed"
    assert jobs(ch) == []


# --- stop -----------------------------------------------------------------------

def test_stop_session(client, env):
    ch, orch, runners = env
    sid = finished_session(client.user_id)
    orch.status[sid] = "running"
    runners.alive.add(sid)

    r = client.post(f"/sessions/{sid}/stop")

    assert r.status_code == 200 and r.json() == {"id": sid, "status": "stopped"}
    assert actions(ch, sid) == ["control.shutdown"]
    assert orch.calls == [("destroy", sid)]
    for q in (actions_queue(sid), results_queue(sid)):
        assert ch.queues[q].deleted == (False, False)
    assert get_session(sid).status == "stopped"


def test_stop_without_a_sandbox(client, env):
    ch, orch, _ = env
    sid = finished_session(client.user_id)
    assert client.post(f"/sessions/{sid}/stop").status_code == 200
    assert actions(ch, sid) == []  # nothing to shut down
    assert get_session(sid).status == "stopped"
    assert client.post("/sessions/nope/stop").status_code == 404


# --- DELETE ----------------------------------------------------------------------

def test_delete_session_stops_its_sandbox_and_deletes_it_all(client, env):
    ch, orch, runners = env
    sid = finished_session(client.user_id, status="running")
    orch.status[sid] = "running"
    runners.alive.add(sid)
    append_event(sid, "note", {})
    with get_db() as s:
        s.add(Usage(user_id=client.user_id, session_id=sid, provider="openrouter", model="m",
                    prompt_tokens=10, completion_tokens=5))

    r = client.delete(f"/sessions/{sid}")

    assert r.status_code == 200 and r.json() == {"id": sid, "deleted": True}
    assert actions(ch, sid) == ["control.shutdown"]
    assert orch.calls == [("destroy", sid)]
    for q in (actions_queue(sid), results_queue(sid)):
        assert ch.queues[q].deleted == (False, False)
    assert get_session(sid) is None and load_events(sid) == []
    assert client.get(f"/sessions/{sid}").status_code == 404
    assert [s["id"] for s in client.get("/sessions").json()] == []
    # its tokens still count against the day's limit
    assert usage.used_today(client.user_id) == 15


def test_delete_a_plain_chat(client, env):
    ch, orch, _ = env
    sid = client.post("/sessions", json={"message": "hi"}).json()["id"]
    orch.calls.clear()
    assert client.delete(f"/sessions/{sid}").status_code == 200
    assert orch.calls == [] and actions(ch, sid) == []
    assert get_session(sid) is None
    assert client.delete(f"/sessions/{sid}").status_code == 404
    assert client.delete("/sessions/nope").status_code == 404


def test_a_sandbox_that_wont_stop_keeps_the_session(client, env, monkeypatch):
    ch, orch, _ = env
    sid = finished_session(client.user_id)

    def fail(sid):
        raise RuntimeError("k8s is down")

    monkeypatch.setattr(sandbox, "destroy_sandbox", fail)
    assert client.delete(f"/sessions/{sid}").status_code == 502
    assert get_session(sid) is not None


# --- startup ---------------------------------------------------------------------

def test_startup_sweeps_crashed_sessions(env):
    create_session("stale00001", task="t", repo=REPO, model="m", status="running")
    with get_db() as s:
        row = s.get(Session, "stale00001")
        row.created_at = utcnow() - timedelta(hours=1)
        s.add(row)
        for ev in s.exec(__import__("sqlmodel").select(SessionEvent)):
            ev.ts = utcnow() - timedelta(minutes=30)
            s.add(ev)

    with TestClient(gateway_app.app):
        pass

    assert get_session("stale00001").status == "interrupted"


@pytest.fixture
def fake_listener(monkeypatch):
    calls = []

    def start(url):
        calls.append(("start", url))
        return asyncio.create_task(asyncio.Event().wait())

    async def stop(task):
        calls.append(("stop", task.cancel()))

    monkeypatch.setattr(live, "start", start)
    monkeypatch.setattr(live, "stop", stop)
    return calls


def test_live_listener_runs_for_the_gateway_lifetime_on_postgres(env, fake_listener, monkeypatch):
    pg = NS(dialect=NS(name="postgresql"), url="postgresql+psycopg://otto:pw@db:5432/otto")
    monkeypatch.setattr(gateway_app, "get_engine", lambda: pg)
    with TestClient(gateway_app.app):
        assert fake_listener == [("start", "postgresql://otto:pw@db:5432/otto")]
    assert fake_listener[1:] == [("stop", True)]


def test_no_live_listener_on_sqlite(env, fake_listener):
    with TestClient(gateway_app.app):
        pass
    assert fake_listener == []



# --- WS /sessions/{sid}/ws --------------------------------------------------------

WS = "wsses00001"


def ws_session(user_id, n_events):
    """A session with events 1..n_events (1 is session.created)."""
    create_session(WS, task="t", repo=REPO, model="m", user_id=user_id)
    for i in range(2, n_events + 1):
        append_event(WS, "note", {"i": i})


def add(client, i, notify=True):
    """Append an event and, like the Postgres listener, notify the gateway's subscribers."""
    seq = append_event(WS, "note", {"i": i})
    if notify:
        client.portal.call(live.publish, WS, seq)
    return seq


def connect(client, after_seq=0, sid=WS, origin=ORIGIN):
    return client.websocket_connect(f"/sessions/{sid}/ws?after_seq={after_seq}",
                                    headers={"origin": origin} if origin else {})


def seqs(ws, n):
    return [ws.receive_json()["seq"] for _ in range(n)]


def test_ws_replays_events_after_after_seq_in_order(client):
    ws_session(client.user_id, 5)
    with connect(client, after_seq=2) as ws:
        got = [ws.receive_json() for _ in range(3)]
        assert [e["seq"] for e in got] == [3, 4, 5]
        assert got[0]["type"] == "note" and got[0]["payload"] == {"i": 3}
        assert set(got[0]) == {"seq", "ts", "type", "payload"} and isinstance(got[0]["ts"], str)
        add(client, 6)
        assert ws.receive_json()["seq"] == 6


def test_ws_streams_events_appended_after_connecting(client):
    ws_session(client.user_id, 1)
    with connect(client) as ws:
        assert ws.receive_json()["type"] == "session.created"
        add(client, 2)
        e = ws.receive_json()
        assert (e["seq"], e["type"], e["payload"]) == (2, "note", {"i": 2})


def test_ws_event_appended_between_subscribe_and_replay_is_sent_once(client, monkeypatch):
    ws_session(client.user_id, 1)
    subscribe = live.subscribe

    def subscribe_then_race(sid):
        q = subscribe(sid)
        seq = append_event(sid, "raced", {})  # committed after subscribing, before the replay reads
        live.publish(sid, seq)
        return q

    monkeypatch.setattr(live, "subscribe", subscribe_then_race)
    with connect(client, after_seq=1) as ws:
        assert ws.receive_json()["type"] == "raced"
        add(client, 3)
        assert ws.receive_json()["seq"] == 3  # not the raced event again


def test_ws_duplicate_notification_is_sent_once(client):
    ws_session(client.user_id, 1)
    with connect(client) as ws:
        assert seqs(ws, 1) == [1]
        seq = add(client, 2)
        client.portal.call(live.publish, WS, seq)
        client.portal.call(live.publish, WS, 1)  # an old one, too
        add(client, 3)
        assert seqs(ws, 2) == [2, 3]


def test_ws_gap_in_notifications_is_filled_in_order(client):
    ws_session(client.user_id, 3)
    with connect(client, after_seq=2) as ws:
        assert seqs(ws, 1) == [3]
        add(client, 4, notify=False)  # 4 is never notified
        add(client, 5)
        assert seqs(ws, 2) == [4, 5]
        add(client, 6)
        assert seqs(ws, 1) == [6]


def test_ws_resync_rereads_after_the_listener_reconnects(client):
    ws_session(client.user_id, 1)
    with connect(client) as ws:
        assert seqs(ws, 1) == [1]
        add(client, 2, notify=False)  # committed while the listener was down
        client.portal.call(live.resync)
        assert seqs(ws, 1) == [2]


def test_ws_unknown_session_is_closed_with_4404(client):
    with pytest.raises(WebSocketDisconnect) as e:
        with connect(client, sid="nosuch0001") as ws:
            ws.receive_json()
    assert e.value.code == 4404


def test_ws_heartbeat(client, monkeypatch):
    monkeypatch.setattr(gateway_app, "PING_INTERVAL", 0.05)
    ws_session(client.user_id, 1)
    with connect(client, after_seq=1) as ws:
        assert ws.receive_json() == {"type": "ping"}
        assert ws.receive_json() == {"type": "ping"}


def test_ws_is_read_only_and_unsubscribes_on_disconnect(client):
    ws_session(client.user_id, 1)
    with connect(client) as ws:
        assert seqs(ws, 1) == [1]
        ws.send_text("hello")  # ignored
        add(client, 2)
        assert seqs(ws, 1) == [2]
        assert WS in live._subscribers
    for _ in range(200):
        if WS not in live._subscribers:
            break
        time.sleep(0.01)
    assert WS not in live._subscribers
    assert types(WS) == ["session.created", "note"]


def test_cors_allows_the_configured_origins(client):
    headers = {"Access-Control-Request-Method": "POST"}
    ok = client.options("/sessions", headers={**headers, "Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = client.options("/sessions", headers={**headers, "Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_ws_stream_error_closes_with_1011(client, monkeypatch):
    ws_session(client.user_id, 1)

    def broken(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(gateway_app, "load_events", broken)
    with pytest.raises(WebSocketDisconnect) as e:
        with connect(client) as ws:
            ws.receive_json()
    assert e.value.code == 1011
    assert WS not in live._subscribers
