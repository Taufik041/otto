"""What the launch needs from the gateway: email-first sign-in, per-IP rate limits, GET /health,
refusing agent work while the workers are offline, and the production settings."""
import asyncio

import pytest
from starlette.requests import Request

from gateway import app as gateway_app, limits, workers
from gateway.errors import Refused
from shared import config
from shared.bus import connect_with_backoff
from shared.db import get_db
from shared.models import Session, SessionEvent
from shared.sessions import create_session, get_session
from sqlmodel import select
from tests.conftest import ORIGIN
from tests.fakes import PASSWORD, connect_github, sign_out, signup

REPO = "Taufik041/otto_test"
INST = 555


# --- POST /auth/email-status -------------------------------------------------------------

def test_email_status_says_whether_an_account_exists(client):
    signup(client, email="taufik@example.com")
    sign_out(client)
    assert client.post("/auth/email-status", json={"email": " Taufik@Example.com"}).json() == {"exists": True}
    assert client.post("/auth/email-status", json={"email": "new@example.com"}).json() == {"exists": False}


def test_email_status_wants_an_email(client):
    assert client.post("/auth/email-status", json={"email": "nope"}).status_code == 422


# --- rate limits --------------------------------------------------------------------------

@pytest.mark.parametrize("name, call", [
    ("login", lambda c: c.post("/auth/login", json={"email": "a@example.com", "password": "wrong password"})),
    ("login", lambda c: c.post("/auth/token", data={"username": "a@example.com", "password": "wrong password"})),
    ("signup", lambda c: c.post("/auth/signup", json={"name": "x", "email": "bad"})),
    ("email_status", lambda c: c.post("/auth/email-status", json={"email": "a@example.com"})),
    ("access_request", lambda c: c.post("/access-requests", json={"github_login": "someone"})),
])
def test_each_public_route_is_rate_limited_per_ip(client, monkeypatch, name, call):
    monkeypatch.setitem(limits.LIMITS, name, (3, 60))
    assert [call(client).status_code != 429 for _ in range(3)] == [True] * 3

    r = call(client)
    assert r.status_code == 429
    assert r.json()["error"] == "rate_limited" and r.json()["detail"]
    assert 1 <= int(r.headers["retry-after"]) <= 61


def test_login_and_token_share_one_limit(client, monkeypatch):
    monkeypatch.setitem(limits.LIMITS, "login", (2, 60))
    client.post("/auth/login", json={"email": "a@example.com", "password": "x"})
    client.post("/auth/token", data={"username": "a@example.com", "password": "x"})
    assert client.post("/auth/login", json={"email": "a@example.com", "password": "x"}).status_code == 429


def test_the_window_slides(monkeypatch):
    monkeypatch.setitem(limits.LIMITS, "login", (10, 60))
    limits.hit("login", "1.2.3.4", now=1000)
    for t in range(9):
        limits.hit("login", "1.2.3.4", now=1020 + t)
    with pytest.raises(Refused) as e:
        limits.hit("login", "1.2.3.4", now=1030)
    assert e.value.error == "rate_limited" and e.value.headers["Retry-After"] == "31"
    limits.hit("login", "1.2.3.4", now=1061)  # the first hit (at 1000) has left the window
    limits.hit("login", "5.6.7.8", now=1030)  # another IP has its own window


def request_from(host, headers=()):
    return Request({"type": "http", "client": (host, 1234),
                    "headers": [(k.lower().encode(), v.encode()) for k, v in headers]})


def test_the_client_ip_is_the_connections_unless_the_proxy_is_trusted(monkeypatch):
    via_cloudflare = request_from("172.16.0.1", [("CF-Connecting-IP", "203.0.113.9")])
    assert limits.client_ip(via_cloudflare) == "172.16.0.1"  # anyone can send the header
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    assert limits.client_ip(via_cloudflare) == "203.0.113.9"
    assert limits.client_ip(request_from("172.16.0.1")) == "172.16.0.1"


def test_a_trusted_proxy_limits_each_client_separately(client, monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    monkeypatch.setitem(limits.LIMITS, "email_status", (1, 60))
    ask = lambda ip: client.post("/auth/email-status", json={"email": "a@example.com"},
                                 headers={"CF-Connecting-IP": ip}).status_code
    assert (ask("203.0.113.1"), ask("203.0.113.2"), ask("203.0.113.1")) == (200, 200, 429)


# --- GET /health ----------------------------------------------------------------------------

def test_health_needs_no_sign_in(client, monkeypatch):
    monkeypatch.setattr(config, "VERSION", "abc123")
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "up", "workers": "online", "version": "abc123", "password_reset": True}
    assert r.headers["cache-control"] == "no-store"


def test_health_is_paused_while_not_accepting(client, monkeypatch):
    monkeypatch.setattr(config, "ACCEPTING", False)
    assert client.get("/health").json()["status"] == "paused"


def test_health_shows_workers_offline(client, env):
    env[1].online = False
    assert client.get("/health").json()["workers"] == "offline"


def test_the_workers_check_is_cached(client, env, monkeypatch):
    orch = env[1]
    client.get("/health")
    orch.online = False
    assert client.get("/health").json()["workers"] == "online"  # still the cached answer
    assert orch.reach_checks == 1
    monkeypatch.setattr(config, "WORKERS_CHECK_SECONDS", 0)
    assert client.get("/health").json()["workers"] == "offline"


def test_health_allows_the_landing_and_app_origins(client, monkeypatch):
    monkeypatch.setattr(config, "LANDING_ORIGINS", ["https://landing.example"])
    landing = client.get("/health", headers={"Origin": "https://landing.example"})
    app = client.get("/health", headers={"Origin": ORIGIN})
    other = client.get("/health", headers={"Origin": "https://evil.example"})
    assert landing.headers["access-control-allow-origin"] == "https://landing.example"
    assert app.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in other.headers


def test_the_landing_origin_gets_nothing_else(client, monkeypatch):
    monkeypatch.setattr(config, "LANDING_ORIGINS", ["https://landing.example"])
    r = client.get("/models", headers={"Origin": "https://landing.example"})
    assert "access-control-allow-origin" not in r.headers


# --- workers offline ------------------------------------------------------------------------

@pytest.fixture
def user(client, fake_github):
    client.user_id = signup(client)["id"]
    connect_github(fake_github, client.user_id, INST, [REPO])
    return client


def offline(env):
    env[1].online = False
    workers.forget()


def sessions() -> list[Session]:
    with get_db() as s:
        return list(s.exec(select(Session)).all())


def test_an_agent_task_is_refused_while_workers_are_offline(user, env):
    offline(env)
    r = user.post("/sessions", json={"repo": REPO, "message": "fix the tests"})

    assert r.status_code == 503
    assert r.json() == {"error": "workers_offline", "detail": workers.OFFLINE}
    assert sessions() == [] and env[1].calls == [] and env[0].default_exchange.published == []


def test_plain_chats_work_while_workers_are_offline(user, env):
    offline(env)
    assert user.post("/sessions", json={"message": "hello"}).status_code == 201
    sid = idle_chat(user.user_id)
    assert user.post(f"/sessions/{sid}/messages", json={"text": "and again"}).status_code == 202


def idle_chat(user_id, sid="abcdef0123", repo=None, status="done"):
    create_session(sid, task="t", repo=repo, model=config.DEFAULT_MODEL, status=status, user_id=user_id)
    return sid


def stored(sid):
    with get_db() as s:
        return [e.type for e in s.exec(select(SessionEvent).where(SessionEvent.session_id == sid))]


def test_a_repo_follow_up_is_refused_with_nothing_stored(user, env):
    sid = idle_chat(user.user_id, repo=REPO)
    before = stored(sid)
    offline(env)

    r = user.post(f"/sessions/{sid}/messages", json={"text": "and the docs too"})

    assert r.status_code == 503 and r.json()["error"] == "workers_offline"
    assert stored(sid) == before and get_session(sid).status == "done"


def test_attaching_a_repo_to_a_plain_chat_is_refused(user, env):
    sid = idle_chat(user.user_id)
    offline(env)
    r = user.post(f"/sessions/{sid}/messages", json={"text": "now in a repo", "repo": REPO})
    assert r.status_code == 503 and get_session(sid).repo is None


def test_retrying_a_repo_chat_is_refused(user, env):
    sid = idle_chat(user.user_id, repo=REPO, status="failed")
    offline(env)
    r = user.post(f"/sessions/{sid}/retry")
    assert r.status_code == 503 and get_session(sid).status == "failed"


def test_a_failed_sandbox_create_makes_the_next_request_check_again(user, env):
    user.get("/health")
    env[1].fail_create = RuntimeError("connection refused")
    assert user.post("/sessions", json={"repo": REPO, "message": "fix"}).status_code == 502
    env[1].online, env[1].fail_create = False, None
    assert user.get("/health").json()["workers"] == "offline"


# --- production settings ----------------------------------------------------------------------

def test_docs_are_off_unless_asked_for(monkeypatch):
    monkeypatch.setattr(config, "DOCS", False)
    assert gateway_app.docs_urls() == {"docs_url": None, "redoc_url": None, "openapi_url": None}
    monkeypatch.setattr(config, "DOCS", True)
    assert gateway_app.docs_urls()["docs_url"] == "/docs"


@pytest.mark.parametrize("frontend, origins, ok", [
    ("https://app.example", ["https://app.example"], True),
    ("http://app.example", ["https://app.example"], False),
    ("https://app.example", ["http://localhost:5173"], False),
])
def test_production_needs_https(monkeypatch, frontend, origins, ok):
    monkeypatch.setattr(config, "PRODUCTION", True)
    monkeypatch.setattr(config, "FRONTEND_URL", frontend)
    monkeypatch.setattr(config, "CORS_ORIGINS", origins)
    if ok:
        gateway_app.check_production()
    else:
        with pytest.raises(RuntimeError, match="production"):
            gateway_app.check_production()


def test_production_defaults(monkeypatch):
    import dotenv, importlib, os

    monkeypatch.setattr(dotenv, "load_dotenv", lambda **kw: None)  # not .env: just this environment
    for k in list(os.environ):
        if k.startswith("OTTO_") or k in ("CORS_ORIGINS", "FRONTEND_URL"):
            monkeypatch.delenv(k)
    monkeypatch.setenv("OTTO_ENV", "production")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example")
    try:
        fresh = importlib.reload(config)
        assert (fresh.PRODUCTION, fresh.COOKIE_SECURE, fresh.DOCS) == (True, True, False)
        assert fresh.CORS_ORIGINS == ["https://app.example"]
        assert fresh.SIGNUP_MODE == "allowlist"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_the_github_callback_url_is_sent_when_set(client, fake_github, monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    monkeypatch.setattr(config, "GITHUB_CALLBACK_URL", "https://api.example/auth/github/callback")
    url = client.post("/auth/github/url", json={"mode": "signin"}).json()["url"]
    assert parse_qs(urlsplit(url).query)["redirect_uri"] == ["https://api.example/auth/github/callback"]


# --- AMQP connections -------------------------------------------------------------------------

def test_the_first_bus_connect_backs_off_until_the_broker_answers(capsys):
    calls, slept = [], []

    async def connect(url):
        calls.append(url)
        if len(calls) < 6:
            raise ConnectionError("refused")
        return "conn"

    async def sleep(s):
        slept.append(s)

    got = asyncio.run(connect_with_backoff(connect, "amqp://u:secret@bus/", "gateway", max_delay=8, sleep=sleep))
    assert got == "conn" and slept == [1, 2, 4, 8, 8]
    out = capsys.readouterr().out
    assert out.count("[gateway] bus connect failed") == 5 and "secret" not in out


def test_repo_chats_can_be_read_stopped_and_deleted_while_workers_are_offline(user, env, monkeypatch):
    from orchestrator import sandbox

    stopped = idle_chat(user.user_id, sid="aaaaaaaaaa", repo=REPO, status="running")
    deleted = idle_chat(user.user_id, sid="bbbbbbbbbb", repo=REPO)
    offline(env)
    monkeypatch.setattr(sandbox, "sandbox_status", lambda sid: pytest.fail("must not ask an offline cluster"))

    assert user.get(f"/sessions/{stopped}").json()["sandbox_status"] == "unknown"
    assert user.post(f"/sessions/{stopped}/stop").status_code == 200
    assert get_session(stopped).status == "stopped"
    assert user.delete(f"/sessions/{deleted}").status_code == 200
    assert get_session(deleted) is None
    assert user.get("/usage").json()["active_sandboxes"] == []
    assert env[1].calls == []  # sandboxes on an unreachable cluster end by themselves
