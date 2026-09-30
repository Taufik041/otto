"""In-memory stand-ins for the bits of aio_pika the runner and brain use."""
import asyncio
import json
from contextlib import asynccontextmanager


class FakeMessage:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.acked = False
        self.rejected = False

    async def ack(self):
        self.acked = True

    @asynccontextmanager
    async def process(self):
        # like aio_pika: ack on clean exit, reject and re-raise on exception
        try:
            yield
        except BaseException:
            self.rejected = True
            raise
        self.acked = True


class FakeQueue:
    def __init__(self, name):
        self.name = name
        self._q = asyncio.Queue()

    def put(self, body):
        msg = FakeMessage(body)
        self._q.put_nowait(msg)
        return msg

    def close(self):
        # ends any iterator once the queued messages are drained
        self._q.put_nowait(None)

    def pending(self):
        return self._q.qsize()

    async def purge(self):
        while not self._q.empty():
            self._q.get_nowait()
        self.purged = getattr(self, "purged", 0) + 1

    async def delete(self, if_unused=True, if_empty=True):
        self.deleted = (if_unused, if_empty)

    def iterator(self):
        return _FakeIterator(self._q)


class _FakeIterator:
    def __init__(self, q):
        self._q = q

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        msg = await self._q.get()
        if msg is None:
            raise StopAsyncIteration
        return msg


class FakeExchange:
    def __init__(self, on_publish=None):
        self.published = []  # (routing_key, decoded body)
        self.on_publish = on_publish

    async def publish(self, message, routing_key):
        body = json.loads(message.body)
        self.published.append((routing_key, body))
        if self.on_publish:
            self.on_publish(routing_key, body)


class FakeChannel:
    def __init__(self):
        self.default_exchange = FakeExchange()
        self.queues = {}

    def queue(self, name):
        return self.queues.setdefault(name, FakeQueue(name))

    async def declare_queue(self, name, durable=False):
        return self.queue(name)

    async def set_qos(self, prefetch_count):
        self.prefetch = prefetch_count

    async def close(self):
        pass


class FakeConnection:
    def __init__(self, channel):
        self._channel = channel
        self.closed = False

    async def channel(self):
        return self._channel

    async def close(self):
        self.closed = True


# --- OpenAI-shaped responses -------------------------------------------------

from types import SimpleNamespace as NS


def llm_tool_calls(*calls, content=None):
    """calls: (name, args_dict) pairs -> a chat completion asking for those tools."""
    tcs = [NS(id=f"call_{i}", function=NS(name=name, arguments=json.dumps(args)))
           for i, (name, args) in enumerate(calls)]
    return NS(choices=[NS(message=NS(content=content, tool_calls=tcs))])


def llm_final(text):
    return NS(choices=[NS(message=NS(content=text, tool_calls=None))])


def auto_reply(ch, results, stdout=lambda action: f"ran {action['kind']}"):
    """Make the fake channel answer every published action on `results`, like a runner."""
    from shared.bus import make_result

    def on_publish(routing_key, action):
        payload = {"exit_code": 0, "stdout": stdout(action), "stderr": ""}
        results.put(make_result(action, True, payload))

    ch.default_exchange.on_publish = on_publish


# --- providers -----------------------------------------------------------------

def use_env(monkeypatch, env):
    """Configure providers and the model catalog as if `env` were the environment."""
    from shared import config

    keys, models = config.provider_keys(env), config.model_catalog(env)
    monkeypatch.setattr(config, "PROVIDER_KEYS", keys)
    monkeypatch.setattr(config, "MODELS", models)
    monkeypatch.setattr(config, "DEFAULT_MODEL", config.default_model(models, keys, env))
    reset_pools()


def reset_pools():
    from brain import providers
    providers.reset()


def fake_openai(monkeypatch, script):
    """Stand in for AsyncOpenAI in brain.providers. script: api_key -> responses (or exceptions to
    raise), popped per call. Returns the calls made, as dicts of base_url, api_key, model, messages."""
    from brain import providers

    calls = []

    class Client:
        def __init__(self, *, api_key, base_url, max_retries=2, **kw):
            self.api_key, self.base_url, self.max_retries = api_key, base_url, max_retries
            self.chat = NS(completions=NS(create=self.create))

        async def create(self, **kw):
            calls.append({"base_url": self.base_url, "api_key": self.api_key, "model": kw["model"],
                          "messages": json.loads(json.dumps(kw["messages"], default=str))})
            r = script[self.api_key].pop(0)
            if isinstance(r, BaseException):
                raise r
            return r

    monkeypatch.setattr(providers, "AsyncOpenAI", Client)
    providers.reset()  # pools cache their clients
    return calls


def fake_clock(monkeypatch, start=1_750_000_000.0):
    """Fake time for brain.providers: sleeping advances it. Returns the list of sleeps."""
    from brain import providers

    t, waits = [start], []

    async def sleep(seconds):
        waits.append(seconds)
        t[0] += seconds

    monkeypatch.setattr(providers, "now", lambda: t[0])
    monkeypatch.setattr(providers, "sleep", sleep)
    return waits


# --- gateway -----------------------------------------------------------------------

class FakeOrchestrator:
    def __init__(self):
        self.calls = []
        self.status = {}          # sid -> sandbox_status
        self.fail_create = None   # exception to raise from create_sandbox

    def create_sandbox(self, sid, repo_url, token=None):
        self.calls.append(("create", sid, repo_url))
        if self.fail_create:
            raise self.fail_create
        self.status[sid] = "running"
        return f"otto-{sid}"

    def remove_sandbox(self, sid, timeout=120, poll=1):
        self.calls.append(("remove", sid))
        existed = self.status.pop(sid, "missing") != "missing"
        return existed

    def destroy_sandbox(self, sid):
        self.calls.append(("destroy", sid))
        self.status.pop(sid, None)

    def sandbox_status(self, sid):
        return self.status.get(sid, "missing")


class FakeRunners:
    """Answers control actions on the fake bus for sessions whose runner is 'alive'."""

    def __init__(self, ch):
        self.ch, self.alive = ch, set()
        ch.default_exchange.on_publish = self.on_publish

    def on_publish(self, key, body):
        from shared.bus import make_result, results_queue

        if key.endswith(".actions") and body["session_id"] in self.alive:
            payload = {"exit_code": 0, "pong": True} if body["kind"] == "control.ping" else {"exit_code": 0}
            self.ch.queue(results_queue(body["session_id"])).put(make_result(body, True, payload))


PASSWORD = "correct horse battery"


def make_user(user_id="u1", **fields):
    """A user row, straight into the database."""
    from shared.db import get_db
    from shared.models import User

    user = User(id=user_id, name=fields.pop("name", user_id), **fields)
    with get_db() as s:
        s.add(user)
    return user


def signup(client, email="taufik@example.com", name="Taufik Khan", password=PASSWORD) -> dict:
    """Sign up through the API; the client keeps the login cookie. Returns GET /me."""
    r = client.post("/auth/signup", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def log_in_as(client, user_id):
    """Put a valid login cookie for user_id on the client, as if they had signed in."""
    from gateway import auth

    client.cookies.set(auth.COOKIE, auth.session_token(user_id))
