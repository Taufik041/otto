"""What the brain learns about unusable providers reaches GET /models (via Postgres) until the
gateway restarts."""
import pytest
from fastapi.testclient import TestClient
from openai import NotFoundError

from brain import loop
from shared import health
from shared.sessions import create_session
from tests.fakes import fake_clock, fake_openai, use_env
from tests.test_providers import no_quota, status_error

KEYS = {"OPENROUTER_API_KEY": "orkey-one", "OPENAI_API_KEY": "oaikey-one", "OTTO_OPENAI_MODELS": "model-a"}


@pytest.mark.asyncio
async def test_a_provider_out_of_credit_is_recorded(monkeypatch):
    use_env(monkeypatch, KEYS)
    fake_clock(monkeypatch)
    fake_openai(monkeypatch, {"orkey-one": [no_quota()]})
    create_session("c1", task="hi", repo=None, model="openrouter:openrouter/free", status="running")

    await loop.chat_session("c1")

    assert health.unusable() == {"openrouter": "quota"}


@pytest.mark.asyncio
async def test_an_unknown_model_is_recorded_for_that_model_only(monkeypatch):
    use_env(monkeypatch, KEYS)
    fake_clock(monkeypatch)
    fake_openai(monkeypatch, {"oaikey-one": [status_error(404, NotFoundError)]})
    create_session("c1", task="hi", repo=None, model="openai:model-a", status="running")

    await loop.chat_session("c1")

    assert health.unusable() == {"openai:model-a": "model"}


def models(client):
    return {m["id"]: (m["available"], m["hint"]) for m in client.get("/models").json()["models"]}


def test_models_shows_an_unusable_provider_as_unavailable_with_its_hint(client, monkeypatch):
    use_env(monkeypatch, KEYS)
    health.mark("openrouter", "quota")
    assert models(client) == {
        "openrouter:openrouter/free": (False, "Out of credit right now. Try another model."),
        "openai:model-a": (True, None),
    }
    health.mark("openai:model-a", "auth")
    assert models(client)["openai:model-a"] == (False, "Not set up correctly. Try another model.")


def test_a_gateway_restart_forgets_it(client, monkeypatch):
    from gateway import app as gateway_app

    use_env(monkeypatch, KEYS)
    health.mark("openrouter", "quota")
    with TestClient(gateway_app.app) as restarted:
        assert models(restarted)["openrouter:openrouter/free"] == (True, None)
    assert health.unusable() == {}


# --- refused up front: a marked model gets a 400 with its hint, before any work starts ----------

from shared import config
from shared.sessions import get_session, set_status
from tests.fakes import connect_github, signup

REPO = "Taufik041/otto_test"
QUOTA_HINT = "Out of credit right now. Try another model."


@pytest.fixture
def user(client, fake_github, monkeypatch):
    use_env(monkeypatch, KEYS)
    client.user_id = signup(client)["id"]
    connect_github(fake_github, client.user_id, 555, [REPO])
    return client


def refused(r, model, hint=QUOTA_HINT):
    assert r.status_code == 400, r.text
    [d] = r.json()["detail"]
    assert (d["loc"], d["input"], d["hint"]) == (["body", "model"], model, hint)
    assert "unavailable" in d["msg"] and hint in d["msg"]


def jobs(env):
    from shared.bus import SESSIONS_QUEUE
    return [b for k, b in env[0].default_exchange.published if k == SESSIONS_QUEUE]


def test_a_new_chat_on_a_marked_model_is_refused(user, env):
    health.mark("openrouter", "quota")
    refused(user.post("/sessions", json={"message": "hi", "model": "openrouter:openrouter/free"}),
            "openrouter:openrouter/free")
    refused(user.post("/sessions", json={"message": "hi", "repo": REPO, "model": "openrouter:openrouter/free"}),
            "openrouter:openrouter/free")
    assert user.get("/sessions").json() == [] and jobs(env) == [] and env[1].calls == []
    # another provider is fine
    assert user.post("/sessions", json={"message": "hi", "model": "openai:model-a"}).status_code == 201


def test_a_new_chat_on_a_marked_default_is_refused_too(user, env, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_MODEL", "openrouter:openrouter/free")
    health.mark("openrouter", "quota")
    refused(user.post("/sessions", json={"message": "hi"}), "openrouter:openrouter/free")
    # the user's own default counts the same way
    health.clear()
    health.mark("openai:model-a", "auth")
    assert user.patch("/me", json={"default_model": "openai:model-a"}).status_code == 200
    refused(user.post("/sessions", json={"message": "hi"}), "openai:model-a", "Not set up correctly. Try another model.")


def test_a_follow_up_switching_to_or_staying_on_a_marked_model_is_refused(user, env):
    sid = user.post("/sessions", json={"message": "hi", "model": "openai:model-a"}).json()["id"]
    set_status(sid, "done")
    before = len(jobs(env))
    health.mark("openrouter", "quota")

    refused(user.post(f"/sessions/{sid}/messages", json={"text": "more", "model": "openrouter:openrouter/free"}),
            "openrouter:openrouter/free")
    health.mark("openai", "quota")  # now the chat's own model too
    refused(user.post(f"/sessions/{sid}/messages", json={"text": "more"}), "openai:model-a")

    row = get_session(sid)
    assert (row.model, row.status, len(jobs(env))) == ("openai:model-a", "done", before)  # not claimed, nothing queued


def test_a_retry_on_a_marked_model_is_refused(user, env):
    sid = user.post("/sessions", json={"message": "hi", "model": "openai:model-a"}).json()["id"]
    set_status(sid, "failed")
    before = len(jobs(env))
    health.mark("openrouter", "quota")

    refused(user.post(f"/sessions/{sid}/retry", json={"model": "openrouter:openrouter/free"}), "openrouter:openrouter/free")
    health.mark("openai:model-a", "model")  # its own model, marked for that model only
    refused(user.post(f"/sessions/{sid}/retry"), "openai:model-a", "Not offered by its provider right now. Try another model.")

    assert (get_session(sid).status, len(jobs(env))) == ("failed", before)
    health.clear()
    assert user.post(f"/sessions/{sid}/retry").status_code == 202
