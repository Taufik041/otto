"""Provider errors that no wait fixes end the turn at once, with a reason the chat can explain."""
import pytest

from brain import loop
from shared.events import load_events
from shared.sessions import create_session, get_session
from tests.fakes import fake_clock, fake_openai, llm_final, use_env
from tests.test_providers import no_quota, status_error
from openai import AuthenticationError

KEYS = {"OPENROUTER_API_KEY": "orkey-one", "OPENROUTER_API_KEY2": "orkey-two"}


def errors(sid):
    return [e.payload for e in load_events(sid) if e.type == "error"]


@pytest.mark.parametrize("error, reason", [(no_quota, "quota"), (lambda: status_error(401, AuthenticationError), "auth")])
@pytest.mark.asyncio
async def test_every_key_unusable_ends_the_turn_with_a_model_error(monkeypatch, error, reason):
    use_env(monkeypatch, KEYS)
    waits = fake_clock(monkeypatch)
    fake_openai(monkeypatch, {"orkey-one": [error()], "orkey-two": [error()]})
    create_session("c1", task="hi", repo=None, model="openrouter:openrouter/free", status="running")

    await loop.chat_session("c1")  # ends quietly: no exception for the worker to log as a crash

    assert get_session("c1").status == "failed"
    [err] = errors("c1")
    assert (err["stage"], err["reason"], err["provider"]) == ("model", reason, "openrouter")
    assert waits == []
    assert "orkey" not in str(load_events("c1")[-1].payload)


@pytest.mark.asyncio
async def test_one_bad_key_of_two_is_not_an_error(monkeypatch):
    use_env(monkeypatch, KEYS)
    fake_clock(monkeypatch)
    fake_openai(monkeypatch, {"orkey-one": [no_quota()], "orkey-two": [llm_final("hello"), llm_final("Greeting")]})
    create_session("c1", task="hi", repo=None, model="openrouter:openrouter/free", status="running")

    await loop.chat_session("c1")

    assert get_session("c1").status == "done" and errors("c1") == []
