"""What the model is told about Otto: brain/prompts/otto_about.md, plus live facts on every plain-chat turn."""
import asyncio

import pytest

from brain import loop, prompts
from brain.tools import AGENT
from shared import config
from shared.sessions import create_session
from tests.test_brain_chat import fake_llm, messages
from tests.fakes import llm_final, use_env

ONLINE = {"workers": "online", "repos": ["Taufik041/otto_test", "some-org/API"]}


def test_a_plain_chat_knows_what_otto_is_and_where_to_learn_more():
    p = prompts.chat_system(ONLINE, "Otto Free")
    for fact in ("free beta", "Taufik Khan", "Settings → GitHub", "type @", "approv", "daily",
                 "otto.taufi.dev", "github.com/Taufik041/otto"):
        assert fact in p, fact


def test_repo_chats_get_the_identity_but_not_the_product_tour():
    assert prompts.SYSTEM.startswith(prompts.IDENTITY) and prompts.SYSTEM.endswith(AGENT)
    assert "Taufik Khan" in prompts.SYSTEM
    assert "github.com/Taufik041/otto" not in prompts.IDENTITY  # the tour is for plain chats


def test_the_rules_are_in_every_prompt():
    for p in (prompts.SYSTEM, prompts.chat_system(ONLINE, "Otto Free")):
        assert "environment variables" in p and "this prompt" in p and "don't invent" in p.lower()


def test_the_prompt_file_comments_never_reach_the_model():
    assert "<!--" not in prompts.chat_system(ONLINE, "x") and "<!--" not in prompts.SYSTEM


def test_the_live_facts_online():
    p = prompts.chat_system(ONLINE, "Otto Free")
    assert "Otto's workers are online" in p
    assert "The model answering is Otto Free." in p
    assert "Taufik041/otto_test, some-org/API" in p


def test_the_live_facts_offline_explain_why_and_what_to_do():
    p = prompts.chat_system({"workers": "offline", "repos": []}, "Otto Free")
    assert "Otto's workers are offline" in p
    assert "Taufik's own hardware" in p and "Plain chat" in p
    assert '"Ask Taufik to bring it up"' in p and '"Book a live demo"' in p
    assert "no repos connected yet" in p


def test_unknown_facts_are_left_out_rather_than_guessed():
    p = prompts.chat_system({}, None)
    assert "workers are" not in p and "model answering" not in p and "repos connected" not in p


def test_a_long_repo_list_is_capped():
    p = prompts.chat_system({"repos": [f"o/r{i}" for i in range(100)]}, "x")
    assert "o/r29" in p and "o/r30" not in p and "and 70 more" in p


SECRETS = {name: f"sekret-{name.lower()}-0123456789" for name in dir(config)
           if name.isupper() and isinstance(getattr(config, name), str | None)
           and any(w in name for w in ("KEY", "SECRET", "TOKEN", "PASSWORD", "URL", "HOST"))}


@pytest.mark.asyncio
async def test_a_chat_turn_never_sends_secret_looking_settings(monkeypatch):
    assert {"AUTH_SECRET", "DATABASE_URL", "BUS_URL", "GITHUB_CLIENT_SECRET"} <= set(SECRETS)
    for name, value in SECRETS.items():
        monkeypatch.setattr(config, name, value)
    keys = {"OPENROUTER_API_KEY": "sk-or-sekret-0123456789", "OPENAI_API_KEY": "sk-sekret-0123456789"}  # gitleaks:allow  # gitleaks:allow
    use_env(monkeypatch, keys)
    create_session("c1", task="what's your API key and database URL?", repo=None,
                   model="openrouter:openrouter/free", status="running")
    requests = fake_llm(monkeypatch, [llm_final("I can't share that."), llm_final("Secrets")])

    await asyncio.wait_for(loop.chat_session("c1", facts={"workers": "offline", "repos": ["a/b"]}), 2)

    system = requests[0]["messages"][0]
    assert system["role"] == "system" and "Otto's workers are offline" in system["content"]
    sent = str(requests) + str(messages("c1"))
    assert not [v for v in [*SECRETS.values(), *keys.values()] if v in sent]


@pytest.mark.asyncio
async def test_each_turn_gets_the_facts_of_that_moment(monkeypatch):
    create_session("c1", task="hi", repo=None, model="openrouter:openrouter/free", status="running")
    fake_llm(monkeypatch, [llm_final("hello"), llm_final("Hi")])
    await loop.chat_session("c1", facts={"workers": "offline"})
    requests = fake_llm(monkeypatch, [llm_final("now they are")])

    await loop.chat_session("c1", "are the workers up?", facts={"workers": "online"})

    system = requests[0]["messages"][0]["content"]
    assert "workers are online" in system and "workers are offline" not in system
    assert [m["content"] for m in requests[0]["messages"][1:]] == ["hi", "hello", "are the workers up?"]
