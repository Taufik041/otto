import pytest

from shared import config, db as shared_db


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
