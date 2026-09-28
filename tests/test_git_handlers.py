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
