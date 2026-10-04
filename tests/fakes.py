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


def llm_tool_calls(*calls, content=None, usage=None):
    """calls: (name, args_dict) pairs -> a chat completion asking for those tools."""
    tcs = [NS(id=f"call_{i}", function=NS(name=name, arguments=json.dumps(args)))
           for i, (name, args) in enumerate(calls)]
    return NS(choices=[NS(message=NS(content=content, tool_calls=tcs))], usage=usage)


def llm_final(text, usage=None):
    return NS(choices=[NS(message=NS(content=text, tool_calls=None))], usage=usage)


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
        def __init__(self, *, api_key, base_url, max_retries=2, timeout=None, **kw):
            self.api_key, self.base_url, self.max_retries, self.timeout = api_key, base_url, max_retries, timeout
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

    def create_sandbox(self, sid, repo_url, installation_id=None, token=None):
        self.calls.append(("create", sid, repo_url, installation_id))
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
    """Sign up through the API; the client sends its access token from now on. Returns the user."""
    r = client.post("/auth/signup", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return r.json()["user"]


def log_in_as(client, user_id):
    """Sign the client in as user_id, as if they had signed in: an access token, and a refresh
    cookie while the user exists."""
    from gateway import auth, tokens
    from shared.db import get_db
    from shared.models import User

    with get_db() as s:
        user = s.get(User, user_id)
    sign_out(client)
    client.headers["Authorization"] = f"Bearer {tokens.access_token(user or User(id=user_id, name='gone'))}"
    if user is not None:
        client.cookies.set(auth.REFRESH_COOKIE, tokens.issue_refresh(user_id), path=auth.REFRESH_PATH)


def sign_out(client):
    """Forget the client's access token and refresh cookie (not GitHub's nonce cookies)."""
    client.headers.pop("Authorization", None)
    client.cookies.delete("otto_refresh")


# --- GitHub ------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code, body, links=None):
        self.status_code, self._body, self.links = status_code, body, links or {}
        self.text = json.dumps(body)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body


class FakeGitHub:
    """Stands in for gateway.github_app.request: canned GitHub answers and a log of the calls.

    Fill in: codes (OAuth code -> user token), users (user token -> GET /user),
    user_installations (user token -> installation ids), installations (id -> account login),
    repos (installation id -> repo dicts). Lists are paged by page_size.
    """
    API = "https://api.github.com"

    def __init__(self):
        self.calls = []                # (method, path)
        self.codes, self.users, self.user_installations = {}, {}, {}
        self.installations, self.repos = {}, {}
        self.minted = []               # (installation id, repositories or None)
        self.page_size = 100
        self.pulls = {}                # full name -> [{number, html_url, title, body, head, base, state}]
        self.pull_error = None         # (status, body): what POST .../pulls answers instead

    def add_user(self, code, gid, login, **extra):
        token = f"ghu_{login}_{code}"
        self.codes[code] = token
        self.users[token] = {"id": gid, "login": login, "name": extra.pop("name", None),
                             "avatar_url": f"https://avatars.githubusercontent.com/u/{gid}", **extra}
        return token

    def add_installation(self, iid, account_login, repos=(), users=()):
        self.installations[iid] = account_login
        self.repos[iid] = [repo(name) if isinstance(name, str) else name for name in repos]
        for token in users:
            self.user_installations.setdefault(token, []).append(iid)

    def paths(self, method=None):
        return [p for m, p in self.calls if method in (None, m)]

    def _page(self, url, items, key, params):
        page = int((params or {}).get("page", 1))
        chunk = items[(page - 1) * self.page_size: page * self.page_size]
        links = {"next": {"url": url.split("?")[0] + f"?page={page + 1}"}} if page * self.page_size < len(items) else {}
        return FakeResponse(200, {"total_count": len(items), key: chunk}, links)

    def __call__(self, method, url, headers=None, params=None, json=None, data=None, **kw):
        from urllib.parse import parse_qsl, urlsplit

        parts = urlsplit(url)
        params = {**dict(parse_qsl(parts.query)), **(params or {})}
        path = parts.path if parts.netloc == "api.github.com" else parts.netloc + parts.path
        self.calls.append((method, path))
        auth_header = (headers or {}).get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").removeprefix("token ")

        if (method, path) == ("POST", "github.com/login/oauth/access_token"):
            if data.get("client_secret") != "test-client-secret":
                return FakeResponse(200, {"error": "incorrect_client_credentials",
                                          "error_description": "The client_id and/or client_secret passed are incorrect.",
                                          "error_uri": "https://docs.github.com/apps/troubleshooting"})
            if data.get("code") not in self.codes:
                return FakeResponse(200, {"error": "bad_verification_code",
                                          "error_description": "The code passed is incorrect or expired."})
            return FakeResponse(200, {"access_token": self.codes[data["code"]], "token_type": "bearer"})
        if path == "/user" and token in self.users:
            return FakeResponse(200, self.users[token])
        if path == "/user/installations" and token in self.users:
            items = [{"id": i, "account": {"login": self.installations[i]}}
                     for i in self.user_installations.get(token, [])]
            return self._page(url, items, "installations", params)
        if method == "POST" and path.startswith("/app/installations/") and path.endswith("/access_tokens"):
            iid = int(path.split("/")[3])
            if token != "app-jwt" or iid not in self.installations:
                return FakeResponse(404, {"message": "Not Found"})
            self.minted.append((iid, (json or {}).get("repositories")))
            return FakeResponse(201, {"token": f"ghs_inst{iid}_{len(self.minted)}",
                                      "expires_at": "2099-01-01T00:00:00Z"})
        if path == "/installation/repositories":
            iid = next((i for i in self.installations if token.startswith(f"ghs_inst{i}_")), None)
            if iid is None:
                return FakeResponse(401, {"message": "Bad credentials"})
            return self._page(url, self.repos[iid], "repositories", params)
        if path.startswith("/repos/") and path.endswith("/pulls"):
            return self._pulls(method, path.removeprefix("/repos/").removesuffix("/pulls"), token, json, params)
        return FakeResponse(404, {"message": f"FakeGitHub has no {method} {path}"})

    def _pulls(self, method, full_name, token, body, params):
        """POST: open a PR (422 if one is open for the head already); GET: list by head/state."""
        if not token.startswith("ghs_inst"):
            return FakeResponse(401, {"message": "Bad credentials"})
        pulls = self.pulls.setdefault(full_name, [])
        owner = full_name.split("/")[0]
        if method == "GET":
            head = (params or {}).get("head", "")
            return FakeResponse(200, [p for p in pulls if f"{owner}:{p['head']}" == head and p["state"] == "open"])
        if self.pull_error:
            return FakeResponse(*self.pull_error)
        if any(p["head"] == body["head"] and p["state"] == "open" for p in pulls):
            return FakeResponse(422, {"message": "Validation Failed", "errors": [
                {"resource": "PullRequest", "code": "custom",
                 "message": f"A pull request already exists for {owner}:{body['head']}."}]})
        n = len(pulls) + 1
        pr = {"number": n, "html_url": f"https://github.com/{full_name}/pull/{n}", "state": "open", **body}
        pulls.append(pr)
        return FakeResponse(201, pr)


def connect_github(fake_github, user_id, iid=555, repos=("Taufik041/otto_test",), account="Taufik041"):
    """user_id has installation iid (on account), which GitHub says can see repos."""
    from shared.db import get_db
    from shared.models import Installation

    fake_github.add_installation(iid, account, repos=repos)
    with get_db() as s:
        s.add(Installation(id=iid, user_id=user_id, account_login=account))


def repo(full_name, private=True, updated_at="2026-09-01T00:00:00Z", default_branch="main"):
    return {"full_name": full_name, "name": full_name.split("/")[1], "private": private,
            "updated_at": updated_at, "default_branch": default_branch}
