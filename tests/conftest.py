import pytest
from fastapi.testclient import TestClient

from shared import config, db as shared_db
from brain import providers as providers_module
from tests.fakes import FakeChannel, FakeConnection, FakeOrchestrator, FakeRunners, use_env

ORIGIN = "http://localhost:5173"  # in the default CORS_ORIGINS


@pytest.fixture(autouse=True)
def no_github(monkeypatch):
    """No real GitHub: .env may configure the App (which would mint real tokens) or a token."""
    monkeypatch.setattr(config, "GITHUB_APP_ID", None)
    monkeypatch.setattr(config, "GITHUB_INSTALLATION_ID", None)
    monkeypatch.setattr(config, "GITHUB_APP_KEY_PATH", "")
    monkeypatch.setattr(config, "GITHUB_TOKEN", None)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    """A fresh SQLite database standing in for Postgres, for every test."""
    monkeypatch.setattr(shared_db, "_engine", None)
    shared_db.init_db(f"sqlite:///{tmp_path / 'otto.db'}")
    engine = shared_db.get_engine()  # a test may swap it out; still close this one
    yield
    engine.dispose()


TEST_ENV = {"OPENROUTER_API_KEY": "or-test-key-1"}


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    """Provider keys and models from TEST_ENV, not from .env or the real environment; no real clients."""
    use_env(monkeypatch, TEST_ENV)

    def no_network(**kw):
        raise AssertionError("a test tried to build a real AsyncOpenAI client; use tests.fakes.fake_openai")

    monkeypatch.setattr(providers_module, "AsyncOpenAI", no_network)


@pytest.fixture(autouse=True)
def accounts(monkeypatch):
    """A known signing secret and limits, whatever .env says; cheap argon2 so signups are fast."""
    from argon2 import PasswordHasher
    from gateway import auth

    cheap = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    monkeypatch.setattr(auth, "hasher", cheap)
    monkeypatch.setattr(auth, "DUMMY_HASH", cheap.hash("dummy"))
    monkeypatch.setattr(config, "AUTH_SECRET", "test-secret-" + "x" * 32)
    monkeypatch.setattr(config, "FRONTEND_URL", "http://localhost:5173")
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    monkeypatch.setattr(config, "DAILY_TOKEN_LIMIT", 50000)


@pytest.fixture
def env(monkeypatch):
    """The gateway with a fake bus, fake runners and a fake orchestrator."""
    from gateway import app as gateway_app
    from orchestrator import sandbox

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
    """A browser-like client: every request is JSON (the gateway refuses other writes)."""
    from gateway import app as gateway_app

    with TestClient(gateway_app.app, headers={"content-type": "application/json"}) as c:
        yield c
