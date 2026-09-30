"""Settings: PATCH /me, POST /me/password, DELETE /me."""
import pytest
from sqlmodel import func, select

from gateway import auth
from shared.db import get_db
from shared.events import append_event
from shared.models import Installation, PasswordReset, Session, SessionEvent, Usage, User
from shared.sessions import create_session, set_status
from tests.fakes import PASSWORD, connect_github, log_in_as, signup, use_env
from tests.test_github_signin import callback, start
from tests.test_usage import spend

REPO = "Taufik041/otto_test"
MODELS = {"OPENROUTER_API_KEY": "k", "OTTO_OPENAI_MODELS": "model-a,model-b", "OPENAI_API_KEY": "k2"}


# --- PATCH /me ------------------------------------------------------------------------

def test_update_name_and_default_model(client, monkeypatch):
    use_env(monkeypatch, MODELS)
    signup(client)

    r = client.patch("/me", json={"name": "  Taufik  ", "default_model": "openai:model-b"})

    assert r.status_code == 200
    assert (r.json()["name"], r.json()["default_model"]) == ("Taufik", "openai:model-b")
    assert client.get("/me").json()["default_model"] == "openai:model-b"
    assert client.patch("/me", json={"name": "Taufik Khan"}).json()["default_model"] == "openai:model-b"
    assert client.patch("/me", json={"default_model": None}).json()["default_model"] is None  # the server's


@pytest.mark.parametrize("body", [{"default_model": "nope"}, {"default_model": "openai:not-in-catalog"},
                                  {"default_model": "openai:model-a"},  # in the catalog, but no key
                                  {"name": "   "}, {"name": None}])
def test_bad_settings_are_422(client, monkeypatch, body):
    use_env(monkeypatch, {"OPENROUTER_API_KEY": "k", "OTTO_OPENAI_MODELS": "model-a"})
    signup(client)
    assert client.patch("/me", json=body).status_code == 422
    assert client.get("/me").json()["default_model"] is None


def test_settings_need_a_login(client):
    assert client.patch("/me", json={"name": "x"}).status_code == 401
    assert client.post("/me/password", json={"current": "a", "new": "b" * 8}).status_code == 401
    assert client.delete("/me").status_code == 401


# --- POST /me/password -------------------------------------------------------------------

def test_change_password(client):
    me = signup(client)
    r = client.post("/me/password", json={"current": PASSWORD, "new": "a whole new password"})
    assert r.status_code == 200
    client.cookies.clear()
    assert client.post("/auth/login", json={"email": me["email"], "password": PASSWORD}).status_code == 401
    assert client.post("/auth/login", json={"email": me["email"], "password": "a whole new password"}).status_code == 200


def test_change_password_needs_the_current_one(client):
    signup(client)
    assert client.post("/me/password", json={"current": "wrong wrong", "new": "a whole new password"}).status_code == 403
    assert client.post("/me/password", json={"current": PASSWORD, "new": "short"}).status_code == 422


def test_a_github_account_has_no_password_to_change(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    callback(client, code="c1", state=start(client))
    r = client.post("/me/password", json={"current": "", "new": "a whole new password"})
    assert r.status_code == 400


# --- DELETE /me ------------------------------------------------------------------------------

def count(model, **where) -> int:
    with get_db() as s:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return s.exec(q).one()


def test_deleting_the_account_removes_everything_of_theirs(client, env, fake_github, capsys):
    ch, orch, runners = env
    other = signup(client, email="other@example.com")["id"]
    create_session("keep000001", task="theirs", repo=None, model="m", user_id=other)
    spend(other, "keep000001", 10)
    client.cookies.clear()

    me = signup(client, email="taufik@example.com")
    connect_github(fake_github, me["id"], 555, [REPO])
    agent = client.post("/sessions", json={"message": "fix", "repo": REPO}).json()["id"]
    chat = client.post("/sessions", json={"message": "hi"}).json()["id"]
    set_status(chat, "done")
    runners.alive.add(agent)
    append_event(agent, "note", {})
    spend(me["id"], agent, 100)
    spend(me["id"], chat, 50)
    client.post("/auth/forgot", json={"email": "taufik@example.com"})
    orch.calls.clear()

    r = client.delete("/me")

    assert r.status_code == 200
    assert orch.calls == [("destroy", agent)]  # the chat had no sandbox
    for model, where in [(User, {"id": me["id"]}), (Session, {"user_id": me["id"]}),
                         (SessionEvent, {"session_id": agent}), (SessionEvent, {"session_id": chat}),
                         (Usage, {"user_id": me["id"]}), (Installation, {"user_id": me["id"]}),
                         (PasswordReset, {"user_id": me["id"]})]:
        assert count(model, **where) == 0, model
    # someone else's things stay
    assert count(User, id=other) == 1 and count(Session, user_id=other) == 1 and count(Usage, user_id=other) == 1
    # and the cookie is gone, and wouldn't work anyway
    assert auth.COOKIE not in client.cookies
    log_in_as(client, me["id"])
    assert client.get("/me").status_code == 401
    client.cookies.clear()
    assert client.post("/auth/login", json={"email": "taufik@example.com", "password": PASSWORD}).status_code == 401
    assert client.get("/repos").status_code == 401


def test_the_email_can_sign_up_again_after_deleting(client):
    signup(client)
    client.delete("/me")
    signup(client)
