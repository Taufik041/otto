"""Settings: PATCH /me, POST /me/password (DELETE /me: test_account_deletion.py)."""
import pytest

from tests.fakes import PASSWORD, sign_out, signup, use_env
from tests.test_github_signin import callback, start

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
    assert client.request("DELETE", "/me", json={"confirm": "DELETE"}).status_code == 401


# --- POST /me/password -------------------------------------------------------------------

def test_change_password(client):
    me = signup(client)
    r = client.post("/me/password", json={"current": PASSWORD, "new": "a whole new password"})
    assert r.status_code == 200
    sign_out(client)
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


# --- DELETE /me: tests/test_account_deletion.py ------------------------------------------------
