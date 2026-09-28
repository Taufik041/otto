import base64
import os
import shutil
import subprocess

import pytest

from shared import config
from runner import handlers
from runner.handlers import REGISTRY

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

TOKEN = "ghs_FakeInstallationToken123"
B64 = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()


def git(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A workspace cloned from a local bare origin, on branch otto/s1 with one new commit."""
    origin = tmp_path / "origin.git"
    ws = os.path.realpath(tmp_path / "ws")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", origin.as_uri(), ws], check=True, capture_output=True)
    open(os.path.join(ws, "a.txt"), "w").write("a\n")
    git("add", "-A", cwd=ws)
    git("commit", "-qm", "base", cwd=ws)
    git("push", "-q", "origin", "HEAD:main", cwd=ws)
    git("checkout", "-qb", "otto/s1", cwd=ws)
    open(os.path.join(ws, "a.txt"), "w").write("b\n")
    git("commit", "-qam", "fix", cwd=ws)
    monkeypatch.setattr(config, "WORKSPACE", ws)
    monkeypatch.setattr(config, "GITHUB_TOKEN", TOKEN)
    return ws, str(origin)


def test_push_sends_the_current_branch_with_upstream(repo):
    ws, origin = repo
    r = REGISTRY["git.push"]({})
    assert r["exit_code"] == 0, r
    assert r["branch"] == "otto/s1"
    assert git("rev-parse", "refs/heads/otto/s1", cwd=origin) == git("rev-parse", "HEAD", cwd=ws)
    assert git("rev-parse", "--abbrev-ref", "@{u}", cwd=ws) == "origin/otto/s1"


def test_push_without_a_token_fails_clearly(repo, monkeypatch):
    ws, origin = repo
    monkeypatch.setattr(config, "GITHUB_TOKEN", None)
    r = REGISTRY["git.push"]({})
    assert r["exit_code"] == 1 and "GITHUB_TOKEN" in r["stderr"]
    assert r["branch"] == "otto/s1"
    assert "otto/s1" not in git("branch", "--list", cwd=origin)


def test_push_on_detached_head_fails(repo):
    ws, _ = repo
    git("checkout", "-q", "--detach", cwd=ws)
    r = REGISTRY["git.push"]({})
    assert r["exit_code"] == 1 and "detached" in r["stderr"]


def test_push_authenticates_per_command_and_never_leaks_the_token(repo, monkeypatch):
    ws, _ = repo
    seen = []

    def chatty_git(argv, timeout=60, env=None):
        # a git that echoes its whole command line back, e.g. in an error
        seen.append(argv)
        text = " ".join(argv)
        return {"exit_code": 128, "stdout": text, "stderr": f"fatal: {text}"}

    real = handlers._run_argv
    monkeypatch.setattr(handlers, "_run_argv",
                        lambda argv, **kw: chatty_git(argv, **kw) if "push" in argv else real(argv, **kw))
    r = REGISTRY["git.push"]({})

    [argv] = seen
    assert argv == ["git", "-c", f"http.extraheader=AUTHORIZATION: basic {B64}",
                    "push", "-u", "origin", "otto/s1"]
    for v in r.values():
        assert TOKEN not in str(v) and B64 not in str(v)
    assert "[REDACTED]" in r["stderr"]


def test_token_is_not_written_to_disk(repo):
    ws, _ = repo
    REGISTRY["git.push"]({})
    found = subprocess.run(["grep", "-rlF", TOKEN, ws], capture_output=True, text=True).stdout
    found += subprocess.run(["grep", "-rlF", B64, ws], capture_output=True, text=True).stdout
    assert found == ""


def test_model_commands_do_not_see_the_token(repo, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    r = REGISTRY["shell.exec"]({"cmd": "env"})
    assert r["exit_code"] == 0 and TOKEN not in r["stdout"]
    assert "PATH=" in r["stdout"]


# --- git.open_pr (urllib mocked; no network) ----------------------------------

import io
import json
import urllib.error
import urllib.request

PR = {"number": 7, "html_url": "https://github.com/Taufik041/otto_test/pull/7"}


class FakeResponse:
    def __init__(self, data, status=200):
        self._body = json.dumps(data).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(url, code, data):
    return urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(json.dumps(data).encode()))


@pytest.fixture
def github(repo, monkeypatch):
    """Route urlopen through `routes`: {(method, url): response data | Exception}."""
    monkeypatch.setattr(config, "REPO_URL", "https://github.com/Taufik041/otto_test.git")
    routes, requests = {}, []

    def urlopen(req, timeout=None):
        body = json.loads(req.data) if req.data else None
        requests.append({"method": req.get_method(), "url": req.full_url, "body": body,
                         "headers": dict(req.header_items()), "timeout": timeout})
        out = routes[(req.get_method(), req.full_url)]
        if isinstance(out, Exception):
            raise out
        return FakeResponse(out)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return routes, requests


PULLS = "https://api.github.com/repos/Taufik041/otto_test/pulls"


def open_pr(**payload):
    return REGISTRY["git.open_pr"]({"title": "Fix discount", "body": "why and how", **payload})


def test_open_pr_success(github, repo):
    ws, _ = repo
    routes, requests = github
    git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop", cwd=ws)
    routes[("POST", PULLS)] = PR

    r = open_pr()

    assert r == {"exit_code": 0, "stdout": PR["html_url"], "stderr": "", **PR}
    [req] = requests
    assert req["body"] == {"title": "Fix discount", "body": "why and how", "head": "otto/s1", "base": "develop"}
    assert req["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert req["timeout"]


def test_open_pr_base_falls_back_to_main_or_uses_the_given_one(github):
    routes, requests = github
    routes[("POST", PULLS)] = PR
    open_pr()
    open_pr(base="release")
    assert [r["body"]["base"] for r in requests] == ["main", "release"]


def test_open_pr_returns_the_existing_pr(github):
    routes, requests = github
    routes[("POST", PULLS)] = http_error(PULLS, 422, {
        "message": "Validation Failed",
        "errors": [{"resource": "PullRequest", "code": "custom",
                    "message": "A pull request already exists for Taufik041:otto/s1."}]})
    existing = f"{PULLS}?head=Taufik041%3Aotto%2Fs1&state=open"
    routes[("GET", existing)] = [PR]

    r = open_pr()

    assert r["exit_code"] == 0 and r["number"] == 7 and r["html_url"] == PR["html_url"]
    assert [q["method"] for q in requests] == ["POST", "GET"]


@pytest.mark.parametrize("error, expected", [
    (lambda: http_error(PULLS, 422, {"message": "Validation Failed", "errors": [
        {"resource": "PullRequest", "code": "custom", "message": "No commits between main and otto/s1"}]}),
     "No commits between main and otto/s1"),
    (lambda: http_error(PULLS, 401, {"message": "Bad credentials"}), "401: Bad credentials"),
    (lambda: urllib.error.URLError("timed out"), "timed out"),
    (lambda: TimeoutError("The read operation timed out"), "timed out"),
])
def test_open_pr_errors_become_exit_code_1(github, error, expected):
    routes, _ = github
    routes[("POST", PULLS)] = error()
    r = open_pr()
    assert r["exit_code"] == 1 and expected in r["stderr"]
    assert TOKEN not in json.dumps(r)


def test_open_pr_without_a_token(github, monkeypatch):
    _, requests = github
    monkeypatch.setattr(config, "GITHUB_TOKEN", None)
    r = open_pr()
    assert r["exit_code"] == 1 and "GITHUB_TOKEN" in r["stderr"]
    assert requests == []
