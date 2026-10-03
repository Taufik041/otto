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
