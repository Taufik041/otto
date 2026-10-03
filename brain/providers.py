"""LLM providers: a pool of API keys per provider, rotated on rate limits and unusable responses.

One pool per provider per worker process, shared by every session it runs. A session only ever
uses the provider and model it was created with: keys rotate within that provider, never across.
"""
import asyncio, re, time
from email.utils import parsedate_to_datetime

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, InternalServerError, RateLimitError

from shared import config

RATE_LIMIT_COOLDOWN = 60  # seconds a key rests after a 429 or unusable response that gives no reset time
SERVER_ERROR_COOLDOWN = 5  # after a 5xx or a connection error: likely not the key's fault
MIN_COOLDOWN = 1
MAX_WAIT = 60  # longest single sleep when every key is cooling down
MIN_ATTEMPTS = 6

sleep = asyncio.sleep
# provider -> {"keys": [...], "until": [epoch seconds per key], "current": index, "clients": {},
#              "dead": {index: reason}, "dead_for": {(index, model): reason}}
_pools = {}


class LLMError(Exception):
    """The provider kept answering without a usable choice."""


class ProviderUnusable(LLMError):
    """No key of the provider can serve this model, and no wait would change that: reason is
    "quota" (out of credit), "auth" (a bad key) or "model" (an unknown model; model is set)."""

    def __init__(self, provider, reason, model=None):
        what = f"model {model!r} on {provider}" if model else provider
        super().__init__(f"{what} is unusable: {reason}")
        self.provider, self.reason, self.model = provider, reason, model


def unusable_reason(error) -> str | None:
    """"quota", "auth" or "model" for an error that no retry or wait fixes; None for one that may
    pass (a real rate limit, a server error)."""
    if not isinstance(error, APIStatusError):
        return None
    status = error.status_code
    if status == 402 or (status == 429 and "insufficient_quota" in (str(error.code), str(error.type))):
        return "quota"  # OpenAI: 429 insufficient_quota; OpenRouter: 402 insufficient credits
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "model"
    return None


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
        _pools[provider] = {"provider": provider, "keys": keys, "until": [0.0] * len(keys), "current": 0,
                            "clients": {}, "dead": {}, "dead_for": {}}
    pool = _pools[provider]
    if not pool["keys"]:
        raise LLMError(f"no API key for provider {provider!r}")
    return pool


def _dead(pool, i, model) -> str | None:
    return pool["dead"].get(i) or pool["dead_for"].get((i, model))


def _next_key(pool, model=None) -> tuple[int, float]:
    """The key to use next and how long to wait first: the current key or the next one that isn't
    cooling down, else the one whose cooldown ends first (waiting at most MAX_WAIT). Keys that
    can't serve `model` are skipped; with none left, ProviderUnusable."""
    n, t = len(pool["keys"]), now()
    alive = [(pool["current"] + step) % n for step in range(n)]
    alive = [i for i in alive if not _dead(pool, i, model)]
    if not alive:
        reasons = [_dead(pool, i, model) for i in range(n)]
        reason = reasons[-1]
        raise ProviderUnusable(pool["provider"], reason, model if reason == "model" else None)
    for i in alive:
        if pool["until"][i] <= t:
            return i, 0
    i = min(alive, key=lambda i: pool["until"][i])
    return i, min(pool["until"][i] - t, MAX_WAIT)


def unusable(provider, model) -> str | None:
    """Why `provider` can't serve `model` in this process (every key dropped), or None."""
    pool = _pools.get(provider)
    if not pool or not pool["keys"]:
        return None
    reasons = [_dead(pool, i, model) for i in range(len(pool["keys"]))]
    return reasons[-1] if all(reasons) else None


def _drop(pool, i, model, reason):
    """Never use key i again in this process (for `model` only, if the model is the problem).
    Logged once, by index: never the key."""
    if reason == "model":
        pool["dead_for"][(i, model)] = reason
        print(f"[brain] {pool['provider']} key #{i} can't serve model {model!r} (model): not using it for that model",
              flush=True)
    else:
        pool["dead"][i] = reason
        print(f"[brain] {pool['provider']} key #{i} is unusable ({reason}): not using it again in this process",
              flush=True)


def _client(provider, pool, i):
    if i not in pool["clients"]:
        # max_retries=0: the SDK would sleep on a 429 itself; rotating to another key is better
        pool["clients"][i] = AsyncOpenAI(api_key=pool["keys"][i], base_url=config.PROVIDER_URLS[provider],
                                         max_retries=0, timeout=config.LLM_TIMEOUT)
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
    MAX_WAIT). After max(MIN_ATTEMPTS, 2 x keys) such failures, or once the waits would pass
    MODEL_WAIT_BUDGET_SECONDS in all, raise LLMError.

    A key that can't work at all (out of credit, a bad key, an unknown model: see
    unusable_reason) is dropped for this process without a wait, and the next key tried; with
    none left, ProviderUnusable. Each switch of key is recorded as llm.key_rotated (indexes only,
    never the key).
    """
    pool = _pool(provider)
    model = kwargs.get("model")
    attempts = max(MIN_ATTEMPTS, 2 * len(pool["keys"]))
    failed = None  # (index, reason) of the last failure
    tries, problem, waited = 0, None, 0.0
    while tries < attempts:
        i, wait = _next_key(pool, model)
        if wait > 0 and waited + wait > config.MODEL_WAIT_BUDGET_SECONDS:
            print(f"[brain] {provider}: waiting {wait:.0f}s more would pass the {config.MODEL_WAIT_BUDGET_SECONDS:.0f}s "
                  "budget; giving up", flush=True)
            break
        if wait > 0:
            waited += wait
            print(f"[brain] every {provider} key is cooling down; waiting {wait:.0f}s", flush=True)
            await sleep(wait)
        if failed and failed[0] != i:
            record("llm.key_rotated", {"provider": provider, "from_index": failed[0], "to_index": i,
                                       "reason": failed[1]})
        pool["current"] = i
        try:
            resp = await _client(provider, pool, i).chat.completions.create(**kwargs)
        except APIStatusError as e:
            if reason := unusable_reason(e):
                _drop(pool, i, model, reason)
                failed = (i, reason)
                continue  # no wait, and no attempt used: the next key, or ProviderUnusable
            if isinstance(e, RateLimitError):
                reason, problem, cooldown = "rate_limited", "rate limited", reset_delay(e) or RATE_LIMIT_COOLDOWN
            elif isinstance(e, InternalServerError):
                reason, problem, cooldown = "server_error", f"{type(e).__name__}: {e}"[:1000], SERVER_ERROR_COOLDOWN
            else:
                raise
        except APIConnectionError as e:
            reason, problem, cooldown = "server_error", f"{type(e).__name__}: {e}"[:1000], SERVER_ERROR_COOLDOWN
        else:
            problem = no_choice(resp)
            if problem is None:
                return resp
            reason, cooldown = "unusable_response", reset_delay(resp) or RATE_LIMIT_COOLDOWN
        tries += 1
        pool["until"][i] = now() + cooldown
        failed = (i, reason)
        print(f"[brain] {provider} key #{i}: {problem}; resting it {cooldown:.0f}s", flush=True)
    raise LLMError(f"no usable LLM response after {tries} attempts; last: {problem}")
