import json
from email.utils import format_datetime
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import httpx2
import pytest
from openai import APIConnectionError, InternalServerError, RateLimitError

from brain import providers
from brain.providers import LLMError
from tests.fakes import fake_clock, fake_openai, llm_final, use_env

# plain strings, so these tests prove the keys are never emitted, without relying on redaction
KEYS = {"OPENROUTER_API_KEY": "orkey-one", "OPENROUTER_API_KEY2": "orkey-two",
        "OPENROUTER_API_KEY3": "orkey-three", "OPENAI_API_KEY": "oaikey-one", "OTTO_OPENAI_MODELS": "model-a"}
T0 = 1_750_000_000.0  # "now", as epoch seconds
REQ = httpx2.Request("POST", "https://example.test/v1/chat/completions")


def rate_limited(headers=None, body=None):
    return RateLimitError("429 Too Many Requests", response=httpx2.Response(429, headers=headers or {}, request=REQ),
                          body=body)


def openrouter_429(reset_s):
    """OpenRouter's shape: the key's limit headers in error.metadata.headers, reset in epoch ms."""
    return rate_limited(body={"message": "Rate limit exceeded: free-models-per-min", "code": 429,
                              "metadata": {"headers": {"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "0",
                                                       "X-RateLimit-Reset": str(int((T0 + reset_s) * 1000))}}})


@pytest.fixture
def clock(monkeypatch):
    return fake_clock(monkeypatch, start=T0)


@pytest.fixture
def events():
    got = []
    return got, lambda type, payload: got.append((type, payload))


def keys_used(calls):
    return [c["api_key"] for c in calls]


async def complete(record, provider="openrouter", model="openrouter/free"):
    return await providers.complete(provider, record, model=model, messages=[{"role": "user", "content": "hi"}])


@pytest.fixture(autouse=True)
def three_keys(monkeypatch):
    use_env(monkeypatch, KEYS)


# --- rotation ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_429_rotates_to_the_next_key_without_sleeping(monkeypatch, clock, events):
    got, record = events
    calls = fake_openai(monkeypatch, {"orkey-one": [rate_limited()], "orkey-two": [llm_final("ok")]})

    resp = await complete(record)

    assert resp.choices[0].message.content == "ok"
    assert keys_used(calls) == ["orkey-one", "orkey-two"]
    assert clock == []
    assert got == [("llm.key_rotated", {"provider": "openrouter", "from_index": 0, "to_index": 1,
                                        "reason": "rate_limited"})]


@pytest.mark.asyncio
async def test_the_pool_is_shared_so_the_next_call_skips_the_cooling_key(monkeypatch, clock, events):
    _, record = events
    calls = fake_openai(monkeypatch, {"orkey-one": [rate_limited()],
                                      "orkey-two": [llm_final("session A"), llm_final("session B")]})

    await complete(record)
    await complete(record)  # another session, same worker process

    assert keys_used(calls) == ["orkey-one", "orkey-two", "orkey-two"]


@pytest.mark.asyncio
async def test_unusable_response_rotates_like_a_429(monkeypatch, clock, events):
    got, record = events
    calls = fake_openai(monkeypatch, {"orkey-one": [NS(choices=None, error={"message": "no capacity"})],
                                      "orkey-two": [NS(choices=[])],
                                      "orkey-three": [llm_final("ok")]})

    await complete(record)

    assert keys_used(calls) == ["orkey-one", "orkey-two", "orkey-three"]
    assert clock == []
    assert [(p["from_index"], p["to_index"], p["reason"]) for _, p in got] == [
        (0, 1, "unusable_response"), (1, 2, "unusable_response")]


@pytest.mark.asyncio
async def test_server_errors_rotate_too(monkeypatch, clock, events):
    got, record = events
    server_error = InternalServerError("502", response=httpx2.Response(502, request=REQ), body=None)
    calls = fake_openai(monkeypatch, {"orkey-one": [server_error], "orkey-two": [APIConnectionError(request=REQ)],
                                      "orkey-three": [llm_final("ok")]})

    await complete(record)

    assert keys_used(calls) == ["orkey-one", "orkey-two", "orkey-three"]
    assert [p["reason"] for _, p in got] == ["server_error", "server_error"]


@pytest.mark.asyncio
async def test_all_keys_cooling_sleeps_until_the_earliest_reset(monkeypatch, clock, events):
    got, record = events
    calls = fake_openai(monkeypatch, {
        "orkey-one": [openrouter_429(reset_s=45)],
        "orkey-two": [rate_limited(headers={"retry-after": "20"}), llm_final("ok")],
        "orkey-three": [rate_limited(headers={"retry-after-ms": "30000"})],
    })

    await complete(record)

    assert clock == [20]  # key two is free first
    assert keys_used(calls) == ["orkey-one", "orkey-two", "orkey-three", "orkey-two"]
    assert [(p["from_index"], p["to_index"]) for _, p in got] == [(0, 1), (1, 2), (2, 1)]


@pytest.mark.asyncio
async def test_sleep_is_capped_at_60s(monkeypatch, clock, events):
    _, record = events
    use_env(monkeypatch, {"OPENROUTER_API_KEY": "orkey-one", "OPENROUTER_API_KEY2": "orkey-two"})
    calls = fake_openai(monkeypatch, {"orkey-one": [openrouter_429(reset_s=3600)],
                                      "orkey-two": [openrouter_429(reset_s=600), llm_final("ok")]})

    await complete(record)

    # key two ends first, but in 600s: sleep 60s at most, then try it anyway
    assert clock == [60]
    assert keys_used(calls) == ["orkey-one", "orkey-two", "orkey-two"]


@pytest.mark.asyncio
async def test_single_key_waits_out_its_cooldown(monkeypatch, clock, events):
    got, record = events
    calls = fake_openai(monkeypatch, {"oaikey-one": [rate_limited(), NS(choices=[]), llm_final("ok")]})

    await complete(record, provider="openai", model="model-a")

    assert clock == [60, 60]
    assert keys_used(calls) == ["oaikey-one"] * 3
    assert got == []  # nothing to rotate to


@pytest.mark.parametrize("n_keys, attempts", [(1, 6), (3, 6), (4, 8)])
@pytest.mark.asyncio
async def test_attempts_are_capped_then_llm_error(monkeypatch, clock, events, n_keys, attempts):
    _, record = events
    env = {f"OPENROUTER_API_KEY{i + 1}": f"orkey-{i}" for i in range(n_keys)}
    use_env(monkeypatch, env)
    calls = fake_openai(monkeypatch, {k: [rate_limited() for _ in range(10)] for k in env.values()})

    with pytest.raises(LLMError, match=f"after {attempts} attempts; last: rate limited"):
        await complete(record)

    assert len(calls) == attempts


@pytest.mark.asyncio
async def test_last_unusable_response_is_in_the_error(monkeypatch, clock, events):
    _, record = events
    calls = fake_openai(monkeypatch, {k: [NS(choices=None, error={"message": "no capacity"})] * 2
                                      for k in ("orkey-one", "orkey-two", "orkey-three")})

    with pytest.raises(LLMError, match="6 attempts.*no capacity"):
        await complete(record)
    assert len(calls) == 6


@pytest.mark.asyncio
async def test_provider_without_keys_fails_at_once(monkeypatch, clock, events):
    _, record = events
    use_env(monkeypatch, {"OPENROUTER_API_KEY": "orkey-one"})
    calls = fake_openai(monkeypatch, {})

    with pytest.raises(LLMError, match="no API key for provider 'openai'"):
        await complete(record, provider="openai", model="model-a")
    assert calls == []


@pytest.mark.asyncio
async def test_no_fallback_to_another_provider(monkeypatch, clock, events):
    """An OpenRouter session never touches the OpenAI client, even with every OpenRouter key limited."""
    _, record = events
    calls = fake_openai(monkeypatch, {"orkey-one": [rate_limited()] * 3, "orkey-two": [rate_limited()] * 3,
                                      "orkey-three": [rate_limited()] * 3, "oaikey-one": [llm_final("nope")]})

    with pytest.raises(LLMError):
        await complete(record)

    assert {c["base_url"] for c in calls} == {"https://openrouter.ai/api/v1"}
    assert "oaikey-one" not in keys_used(calls)
    assert {c["model"] for c in calls} == {"openrouter/free"}


@pytest.mark.asyncio
async def test_rotation_events_never_contain_key_material(monkeypatch, clock, events):
    got, record = events
    fake_openai(monkeypatch, {"orkey-one": [rate_limited(headers={"retry-after": "5"}), llm_final("ok")],
                              "orkey-two": [openrouter_429(reset_s=10)],
                              "orkey-three": [NS(choices=None, error={"message": "bad"})]})

    await complete(record)

    assert got and all(t == "llm.key_rotated" for t, _ in got)
    assert all(set(p) == {"provider", "from_index", "to_index", "reason"} for _, p in got)
    text = json.dumps(got)
    for key in KEYS.values():
        assert key not in text


# --- clients -------------------------------------------------------------------

def test_clients_are_cached_per_key_and_the_sdk_does_not_retry(monkeypatch):
    calls = fake_openai(monkeypatch, {})
    a, b = providers.get_client("openrouter"), providers.get_client("openrouter")
    assert a is b
    assert (a.api_key, a.base_url, a.max_retries) == ("orkey-one", "https://openrouter.ai/api/v1", 0)
    c = providers.get_client("openai")
    assert (c.api_key, c.base_url) == ("oaikey-one", "https://api.openai.com/v1")
    assert calls == []


# --- reset times ---------------------------------------------------------------

def test_reset_delay(monkeypatch):
    monkeypatch.setattr(providers, "now", lambda: T0)
    delay = providers.reset_delay
    at = datetime.fromtimestamp(T0 + 90, timezone.utc)
    assert delay(rate_limited(headers={"retry-after-ms": "1500"})) == 1.5
    assert delay(rate_limited(headers={"retry-after": "12"})) == 12
    assert delay(rate_limited(headers={"retry-after": format_datetime(at, usegmt=True)})) == 90
    assert delay(rate_limited(headers={"x-ratelimit-reset": str(int((T0 + 7) * 1000))})) == 7  # epoch ms
    assert delay(rate_limited(headers={"X-RateLimit-Reset": str(int(T0 + 8))})) == 8  # epoch s
    assert delay(openrouter_429(reset_s=42)) == 42
    assert delay(NS(choices=None, error={"message": "x", "metadata": {"headers": {"Retry-After": "3"}}})) == 3
    # OpenAI: durations per limit; wait for the later one
    assert delay(rate_limited(headers={"x-ratelimit-reset-requests": "1m30s",
                                       "x-ratelimit-reset-tokens": "250ms"})) == 90
    assert delay(rate_limited(headers={"retry-after": "0"})) == 1  # never 0: that would busy-loop
    assert delay(openrouter_429(reset_s=-5)) == 1  # already past
    assert delay(rate_limited()) is None
    assert delay(rate_limited(headers={"retry-after": "soon"})) is None
    assert delay(NS(choices=[])) is None
    assert delay(None) is None
