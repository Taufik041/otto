import shutil

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
    monkeypatch.setattr(config, "GITHUB_CLIENT_ID", None)
    monkeypatch.setattr(config, "GITHUB_CLIENT_SECRET", None)
    monkeypatch.setattr(config, "GITHUB_APP_SLUG", None)

    from gateway import github_app

    def no_network(*a, **kw):
        raise AssertionError("a test tried to call GitHub; use the fake_github fixture")

    monkeypatch.setattr(github_app, "request", no_network)
    github_app.forget_all()


@pytest.fixture
def fake_github(monkeypatch):
    """GitHub OAuth and the App configured, answered by a FakeGitHub."""
    from gateway import github_app
    from tests.fakes import FakeGitHub

    gh = FakeGitHub()
    monkeypatch.setattr(config, "GITHUB_CLIENT_ID", "Iv1.testclient")
    monkeypatch.setattr(config, "GITHUB_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(config, "GITHUB_APP_SLUG", "ottoci")
    monkeypatch.setattr(config, "GITHUB_APP_ID", "12345")
    monkeypatch.setattr(config, "GITHUB_APP_KEY_PATH", "/nonexistent/key.pem")
    monkeypatch.setattr(github_app, "make_jwt", lambda: "app-jwt")
    monkeypatch.setattr(github_app, "request", gh)
    return gh


@pytest.fixture(scope="session")
def migrated(tmp_path_factory):
    """An SQLite database migrated to head, made once: each test gets a copy (migrating costs ~20ms)."""
    path = tmp_path_factory.mktemp("template") / "otto.db"
    shared_db.init_db(f"sqlite:///{path}")
    shared_db.get_engine().dispose()
    shared_db._engine = None
    return path


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch, migrated):
    """A fresh SQLite database standing in for Postgres, for every test."""
    shutil.copy(migrated, tmp_path / "otto.db")
    engine = shared_db._make_engine(f"sqlite:///{tmp_path / 'otto.db'}")
    monkeypatch.setattr(shared_db, "_engine", engine)
    yield
    engine.dispose()  # a test may swap the engine out; still close this one


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
