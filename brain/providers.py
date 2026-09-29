"""LLM providers: a pool of API keys per provider, rotated on rate limits and unusable responses.

One pool per provider per worker process, shared by every session it runs. A session only ever
uses the provider and model it was created with: keys rotate within that provider, never across.
"""
import asyncio, re, time
from email.utils import parsedate_to_datetime

from openai import APIConnectionError, AsyncOpenAI, InternalServerError, RateLimitError

from shared import config

RATE_LIMIT_COOLDOWN = 60  # seconds a key rests after a 429 or unusable response that gives no reset time
SERVER_ERROR_COOLDOWN = 5  # after a 5xx or a connection error: likely not the key's fault
MIN_COOLDOWN = 1
MAX_WAIT = 60  # longest single sleep when every key is cooling down
MIN_ATTEMPTS = 6

sleep = asyncio.sleep
_pools = {}  # provider -> {"keys": [...], "until": [epoch seconds per key], "current": index, "clients": {}}


class LLMError(Exception):
    """The provider kept answering without a usable choice."""


def now() -> float:
    return time.time()


def reset():
    """Forget every pool (its cooldowns and clients); they are rebuilt from config on next use."""
    _pools.clear()


def no_choice(resp) -> str | None:
    """Why resp carries no usable choice, or None when it does."""
    if resp is None:
        return "empty response"
    # some providers answer 200 with {"error": ...}; the SDK keeps unknown body fields as attributes
    error = getattr(resp, "error", None)
    if error:
        return f"provider error: {error}"[:1000]
    if not getattr(resp, "choices", None):
        return "response has no choices"
    return None


def _pool(provider) -> dict:
    if provider not in config.PROVIDER_URLS:
        raise LLMError(f"unknown provider {provider!r}")
    if provider not in _pools:
        keys = list(config.PROVIDER_KEYS.get(provider, []))
        _pools[provider] = {"keys": keys, "until": [0.0] * len(keys), "current": 0, "clients": {}}
    pool = _pools[provider]
    if not pool["keys"]:
        raise LLMError(f"no API key for provider {provider!r}")
    return pool


def _next_key(pool) -> tuple[int, float]:
    """The key to use next and how long to wait first: the current key or the next one that isn't
    cooling down, else the one whose cooldown ends first (waiting at most MAX_WAIT)."""
    n, t = len(pool["keys"]), now()
    for step in range(n):
        i = (pool["current"] + step) % n
        if pool["until"][i] <= t:
            return i, 0
    i = min(range(n), key=lambda i: pool["until"][i])
    return i, min(pool["until"][i] - t, MAX_WAIT)


def _client(provider, pool, i):
    if i not in pool["clients"]:
        # max_retries=0: the SDK would sleep on a 429 itself; rotating to another key is better
        pool["clients"][i] = AsyncOpenAI(api_key=pool["keys"][i], base_url=config.PROVIDER_URLS[provider],
                                         max_retries=0)
    return pool["clients"][i]


def get_client(provider):
    """An AsyncOpenAI client for the provider's current usable key (cached per key)."""
    pool = _pool(provider)
    return _client(provider, pool, _next_key(pool)[0])


def _limit_headers(source) -> dict:
    """Lower-cased rate-limit headers: an HTTP error's own, plus any in the error body's metadata
    (OpenRouter puts the key's X-RateLimit-* there)."""
    headers = {}
    response = getattr(source, "response", None)
    if response is not None:
        headers.update((k.lower(), v) for k, v in response.headers.items())
    for body in (getattr(source, "body", None), getattr(source, "error", None)):
        meta = body.get("metadata") if isinstance(body, dict) else None
        if isinstance(meta, dict) and isinstance(meta.get("headers"), dict):
            headers.update((str(k).lower(), v) for k, v in meta["headers"].items())
    return headers


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _http_date(value) -> float | None:
    try:
        return parsedate_to_datetime(value).timestamp() - now()
    except (TypeError, ValueError, IndexError):
        return None


def _epoch(value) -> float | None:
    """X-RateLimit-Reset: epoch ms (OpenRouter) or epoch s; small values are seconds from now."""
    v = _number(value)
    if v is None:
        return None
    return v / 1000 - now() if v > 1e11 else v - now() if v > 1e9 else v


DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}


def _duration(value) -> float | None:
    """OpenAI's x-ratelimit-reset-*: "250ms", "20s", "1m30s"."""
    if not isinstance(value, str) or not re.fullmatch(f"(?:{DURATION.pattern})+", value):
        return None
    return sum(float(n) * UNITS[unit] for n, unit in DURATION.findall(value))


def reset_delay(source) -> float | None:
    """Seconds until a rate-limited key may be used again, from an error or an error response;
    None when it doesn't say."""
    h = _limit_headers(source)
    ms = _number(h.get("retry-after-ms"))
    openai = [d for d in (_duration(h.get("x-ratelimit-reset-requests")),
                          _duration(h.get("x-ratelimit-reset-tokens"))) if d is not None]
    for delay in (None if ms is None else ms / 1000,
                  _number(h.get("retry-after")), _http_date(h.get("retry-after")),
                  _epoch(h.get("x-ratelimit-reset")),
                  max(openai, default=None)):
        if delay is not None:
            return max(delay, MIN_COOLDOWN)
    return None


async def complete(provider, record, **kwargs):
    """One chat completion from `provider`, rotating between its keys.

    A key that is rate limited, answers without a usable choice, or fails with a server error
    cools down (until its reset time if the error says, else RATE_LIMIT_COOLDOWN) and the next
    key is tried at once. With every key cooling down, sleep until the first is free (at most
    MAX_WAIT). After max(MIN_ATTEMPTS, 2 x keys) attempts, raise LLMError. Each switch of key is
    recorded as llm.key_rotated (indexes only, never the key).
    """
    pool = _pool(provider)
    attempts = max(MIN_ATTEMPTS, 2 * len(pool["keys"]))
    failed = None  # (index, reason) of the last failure
    for _ in range(attempts):
        i, wait = _next_key(pool)
        if wait > 0:
            print(f"[brain] every {provider} key is cooling down; waiting {wait:.0f}s", flush=True)
            await sleep(wait)
        if failed and failed[0] != i:
            record("llm.key_rotated", {"provider": provider, "from_index": failed[0], "to_index": i,
                                       "reason": failed[1]})
        pool["current"] = i
        try:
            resp = await _client(provider, pool, i).chat.completions.create(**kwargs)
        except RateLimitError as e:
            reason, problem, cooldown = "rate_limited", "rate limited", reset_delay(e) or RATE_LIMIT_COOLDOWN
        except (APIConnectionError, InternalServerError) as e:
            reason, problem, cooldown = "server_error", f"{type(e).__name__}: {e}"[:1000], SERVER_ERROR_COOLDOWN
        else:
            problem = no_choice(resp)
            if problem is None:
                return resp
            reason, cooldown = "unusable_response", reset_delay(resp) or RATE_LIMIT_COOLDOWN
        pool["until"][i] = now() + cooldown
        failed = (i, reason)
        print(f"[brain] {provider} key #{i}: {problem}; resting it {cooldown:.0f}s", flush=True)
    raise LLMError(f"no usable LLM response after {attempts} attempts; last: {problem}")
