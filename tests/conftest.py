import pytest

from shared import db as shared_db


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    """A fresh SQLite database standing in for Postgres, for every test."""
    monkeypatch.setattr(shared_db, "_engine", None)
    shared_db.init_db(f"sqlite:///{tmp_path / 'otto.db'}")
    yield
    shared_db.get_engine().dispose()
