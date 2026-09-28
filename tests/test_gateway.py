import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from orchestrator import sandbox
from shared import config
from shared.bus import SESSIONS_QUEUE, actions_queue, make_result, results_queue
from shared.db import get_db
from shared.events import append_event, load_events
from shared.models import Session, SessionEvent, utcnow
from shared.sessions import create_session, get_session, set_status
from gateway import app as gateway_app
from tests.fakes import FakeChannel, FakeConnection

REPO = "https://github.com/Taufik041/otto_test"


class FakeOrchestrator:
    def __init__(self):
        self.calls = []
        self.status = {}          # sid -> sandbox_status
        self.fail_create = None   # exception to raise from create_sandbox

    def create_sandbox(self, sid, repo_url, token=None):
        self.calls.append(("create", sid, repo_url))
        if self.fail_create:
            raise self.fail_create
        self.status[sid] = "running"
        return f"otto-{sid}"

    def remove_sandbox(self, sid, timeout=120, poll=1):
        self.calls.append(("remove", sid))
        existed = self.status.pop(sid, "missing") != "missing"
        return existed

    def destroy_sandbox(self, sid):
        self.calls.append(("destroy", sid))
        self.status.pop(sid, None)

    def sandbox_status(self, sid):
        return self.status.get(sid, "missing")


class FakeRunners:
    """Answers control actions on the fake bus for sessions whose runner is 'alive'."""

    def __init__(self, ch):
        self.ch, self.alive = ch, set()
        ch.default_exchange.on_publish = self.on_publish

    def on_publish(self, key, body):
        if key.endswith(".actions") and body["session_id"] in self.alive:
            payload = {"exit_code": 0, "pong": True} if body["kind"] == "control.ping" else {"exit_code": 0}
            self.ch.queue(results_queue(body["session_id"])).put(make_result(body, True, payload))


@pytest.fixture
def env(monkeypatch):
    ch = FakeChannel()
    orch = FakeOrchestrator()
    for name in ("create_sandbox", "remove_sandbox", "destroy_sandbox", "sandbox_status"):
        monkeypatch.setattr(sandbox, name, getattr(orch, name))

    async def connect(url):
        return FakeConnection(ch)

    monkeypatch.setattr(gateway_app, "connect_robust", connect)
    monkeypatch.setattr(gateway_app, "PING_TIMEOUT", 0.2)
    monkeypatch.setattr(config, "MAX_ACTIVE_SESSIONS", 3)
    return ch, orch, FakeRunners(ch)


@pytest.fixture
def client(env):
    with TestClient(gateway_app.app) as c:
        yield c


def jobs(ch):
    return [body for key, body in ch.default_exchange.published if key == SESSIONS_QUEUE]


def actions(ch, sid):
    return [body["kind"] for key, body in ch.default_exchange.published if key == actions_queue(sid)]


def types(sid):
    return [e.type for e in load_events(sid)]


# --- POST /sessions --------------------------------------------------------------

def test_create_session(client, env):
    ch, orch, _ = env
    r = client.post("/sessions", json={"repo_url": REPO, "task": "fix the tests"})

    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json() == {"id": sid, "status": "queued"}
    assert len(sid) == 10 and sid.isalnum() and sid == sid.lower()
    row = get_session(sid)
    assert (row.status, row.repo_url, row.task) == ("queued", REPO, "fix the tests")
    assert orch.calls == [("create", sid, REPO)]
    assert jobs(ch) == [{"type": "start", "session_id": sid}]
    assert types(sid) == ["session.created", "session.status"]


def test_ids_are_unique(client):
    ids = {client.post("/sessions", json={"repo_url": REPO, "task": "t"}).json()["id"] for _ in range(3)}
    assert len(ids) == 3


def test_create_sandbox_failure_is_502_and_failed(client, env):
    ch, orch, _ = env
    orch.fail_create = RuntimeError("k8s says no; token ghs_abcdef123")

    r = client.post("/sessions", json={"repo_url": REPO, "task": "t"})

    assert r.status_code == 502
    assert "ghs_" not in r.text
    [row] = [get_session(s["id"]) for s in client.get("/sessions").json()]
    assert row.status == "failed"
    err = [e for e in load_events(row.id) if e.type == "error"]
    assert err and "k8s says no" in err[0].payload["message"] and "ghs_" not in json.dumps(err[0].payload)
    assert jobs(ch) == []


def test_too_many_active_sessions_is_429(client, env, monkeypatch):
    monkeypatch.setattr(config, "MAX_ACTIVE_SESSIONS", 2)
    create_session("old1", task="t", repo_url=REPO, model="m", status="done")  # not active
    assert client.post("/sessions", json={"repo_url": REPO, "task": "a"}).status_code == 201
    assert client.post("/sessions", json={"repo_url": REPO, "task": "b"}).status_code == 201
    r = client.post("/sessions", json={"repo_url": REPO, "task": "c"})
    assert r.status_code == 429
    assert len(env[1].calls) == 2


def test_bad_request_is_422(client, env):
    assert client.post("/sessions", json={"repo_url": "not a repo", "task": "t"}).status_code == 422
    assert client.post("/sessions", json={"repo_url": REPO, "task": ""}).status_code == 422
    assert env[1].calls == []


# --- reading ---------------------------------------------------------------------

def test_list_get_and_events(client, env):
    a = client.post("/sessions", json={"repo_url": REPO, "task": "first"}).json()["id"]
    b = client.post("/sessions", json={"repo_url": REPO, "task": "second"}).json()["id"]

    listed = client.get("/sessions").json()
    assert [s["id"] for s in listed] == [b, a]
    assert set(listed[0]) == {"id", "repo_url", "task", "status", "pr_url", "created_at"}

    one = client.get(f"/sessions/{a}").json()
    assert one["id"] == a and one["sandbox_status"] == "running"
    assert one["work_branch"] is None and one["pr_url"] is None
    assert client.get("/sessions/nope").status_code == 404

    evs = client.get(f"/sessions/{a}/events").json()
    assert [e["seq"] for e in evs] == [1, 2] and evs[0]["type"] == "session.created"
    assert [e["seq"] for e in client.get(f"/sessions/{a}/events?after_seq=1").json()] == [2]
    assert client.get("/sessions/nope/events").status_code == 404


# --- follow-ups ------------------------------------------------------------------

def finished_session(sid="abcdef0123", status="done"):
    create_session(sid, task="t", repo_url=REPO, model="m", status=status)
    return sid


def test_follow_up_reuses_a_warm_sandbox(client, env):
    ch, orch, runners = env
    sid = finished_session()
    orch.status[sid] = "running"
    runners.alive.add(sid)

    r = client.post(f"/sessions/{sid}/messages", json={"text": "also add a test"})

    assert r.status_code == 202 and r.json() == {"id": sid, "status": "queued"}
    assert orch.calls == []
    assert actions(ch, sid) == ["control.ping"]
    assert "sandbox.reused" in types(sid) and "sandbox.recreated" not in types(sid)
    assert jobs(ch) == [{"type": "resume", "session_id": sid, "text": "also add a test"}]
    assert get_session(sid).status == "queued"


@pytest.mark.parametrize("state", ["running", "finished", "missing"])
def test_follow_up_recreates_a_dead_sandbox(client, env, state):
    ch, orch, _ = env
    sid = finished_session()
    if state != "missing":
        orch.status[sid] = state  # "running" but its runner doesn't answer the ping
    ch.queue(actions_queue(sid)).put({"stale": "action"})

    r = client.post(f"/sessions/{sid}/messages", json={"text": "more"})

    assert r.status_code == 202
    assert actions(ch, sid) == (["control.ping"] if state == "running" else [])
    assert orch.calls == [("remove", sid), ("create", sid, REPO)]
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
    sid = finished_session(status=status)
    r = client.post(f"/sessions/{sid}/messages", json={"text": "more"})
    assert r.status_code == 409
    assert orch.calls == [] and jobs(ch) == [] and actions(ch, sid) == []
    assert get_session(sid).status == status


def test_follow_up_on_missing_session_is_404(client):
    assert client.post("/sessions/nope/messages", json={"text": "x"}).status_code == 404


def test_follow_up_recreate_failure_is_502(client, env):
    ch, orch, _ = env
    sid = finished_session()
    orch.fail_create = RuntimeError("quota")
    r = client.post(f"/sessions/{sid}/messages", json={"text": "more"})
    assert r.status_code == 502
    assert get_session(sid).status == "failed"
    assert jobs(ch) == []


# --- DELETE ----------------------------------------------------------------------

def test_delete_session(client, env):
    ch, orch, runners = env
    sid = finished_session()
    orch.status[sid] = "running"
    runners.alive.add(sid)

    r = client.delete(f"/sessions/{sid}")

    assert r.status_code == 200 and r.json() == {"id": sid, "status": "stopped"}
    assert actions(ch, sid) == ["control.shutdown"]
    assert orch.calls == [("destroy", sid)]
    for q in (actions_queue(sid), results_queue(sid)):
        assert ch.queues[q].deleted == (False, False)
    assert get_session(sid).status == "stopped"


def test_delete_without_a_sandbox(client, env):
    ch, orch, _ = env
    sid = finished_session()
    assert client.delete(f"/sessions/{sid}").status_code == 200
    assert actions(ch, sid) == []  # nothing to shut down
    assert get_session(sid).status == "stopped"
    assert client.delete("/sessions/nope").status_code == 404


# --- startup ---------------------------------------------------------------------

def test_startup_sweeps_crashed_sessions(env):
    create_session("stale00001", task="t", repo_url=REPO, model="m", status="running")
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
