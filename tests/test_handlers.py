import os
import shutil
import subprocess

import pytest

from shared import config
from runner import handlers
from runner.handlers import REGISTRY, _resolve


@pytest.fixture(autouse=True)
def ws(tmp_path, monkeypatch):
    # realpath so _resolve's startswith check matches
    path = os.path.realpath(tmp_path)
    monkeypatch.setattr(config, "WORKSPACE", path)
    return path


def call(kind, payload):
    return REGISTRY[kind](payload)


def write(ws, name, text):
    p = os.path.join(ws, name)
    with open(p, "w") as f:
        f.write(text)
    return p


def test_shell_exec_echo():
    r = call("shell.exec", {"cmd": "echo hi"})
    assert r == {"exit_code": 0, "stdout": "hi\n", "stderr": ""}


def test_shell_exec_runs_in_workspace(ws):
    assert call("shell.exec", {"cmd": "pwd"})["stdout"].strip() == ws


def test_output_capped_at_10k():
    r = call("shell.exec", {"cmd": "yes | head -c 50000"})
    assert len(r["stdout"]) == 10_000


def test_fs_read_range(ws):
    write(ws, "f.txt", "".join(f"line{i}\n" for i in range(1, 11)))
    r = call("fs.read", {"path": "f.txt", "start_line": 3, "end_line": 5})
    assert r["exit_code"] == 0
    assert r["stdout"] == "line3\nline4\nline5\n"


def test_fs_read_default_window_is_200(ws):
    write(ws, "f.txt", "".join(f"line{i}\n" for i in range(1, 451)))
    r = call("fs.read", {"path": "f.txt", "start_line": 10})
    lines = r["stdout"].splitlines()
    assert lines[0] == "line10"
    assert lines[-1] == "line210"


def test_fs_read_small_file_whole(ws):
    write(ws, "f.txt", "a\nb\n")
    assert call("fs.read", {"path": "f.txt"})["stdout"] == "a\nb\n"


def test_fs_read_large_file_without_range_errors(ws):
    write(ws, "big.txt", "x\n" * 450)
    r = call("fs.read", {"path": "big.txt"})
    assert r["exit_code"] == 1
    assert "450 lines" in r["stderr"]
    assert "start_line" in r["stderr"]


def test_fs_write_new_file(ws):
    r = call("fs.write", {"path": "new.txt", "content": "hello\n"})
    assert r["exit_code"] == 0
    assert "wrote 6 bytes" in r["stdout"]
    assert open(os.path.join(ws, "new.txt")).read() == "hello\n"


def test_fs_write_shrink_guard_refuses(ws):
    p = write(ws, "f.txt", "x" * 100)
    r = call("fs.write", {"path": "f.txt", "content": "y" * 10})
    assert r["exit_code"] == 1
    assert "refusing to write" in r["stderr"]
    assert "fs_replace" in r["stderr"]
    assert open(p).read() == "x" * 100


def test_fs_write_allows_half_size(ws):
    p = write(ws, "f.txt", "x" * 100)
    r = call("fs.write", {"path": "f.txt", "content": "y" * 50})
    assert r["exit_code"] == 0
    assert open(p).read() == "y" * 50


def test_fs_replace_zero_matches(ws):
    write(ws, "f.txt", "a = 1\n")
    r = call("fs.replace", {"path": "f.txt", "old_str": "b = 2", "new_str": "b = 3"})
    assert r["exit_code"] == 1
    assert "old_str not found" in r["stderr"]


def test_fs_replace_one_match(ws):
    p = write(ws, "f.txt", "a = 1\nb = 2\n")
    r = call("fs.replace", {"path": "f.txt", "old_str": "b = 2", "new_str": "b = 3"})
    assert r["exit_code"] == 0
    assert "replaced 1 occurrence" in r["stdout"]
    assert open(p).read() == "a = 1\nb = 3\n"


def test_fs_replace_two_matches(ws):
    p = write(ws, "f.txt", "x\nx\n")
    r = call("fs.replace", {"path": "f.txt", "old_str": "x", "new_str": "y"})
    assert r["exit_code"] == 1
    assert "appears 2 times" in r["stderr"]
    assert open(p).read() == "x\nx\n"


def test_resolve_rejects_escape():
    with pytest.raises(ValueError, match="escapes workspace"):
        _resolve("../etc/passwd")


def test_resolve_inside_workspace(ws):
    assert _resolve("a/b.txt") == os.path.join(ws, "a", "b.txt")


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
def test_code_search_truncation_notice(ws):
    write(ws, "many.txt", "needle\n" * 60)
    r = call("code.search", {"pattern": "needle"})
    lines = r["stdout"].splitlines()
    assert sum(1 for l in lines if "needle" in l and "truncated" not in l) == 50
    assert "results truncated at 50 matches" in r["stdout"]
    assert "NOT the total count" in r["stdout"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_commit(ws):
    subprocess.run(["git", "init", "-q", ws], check=True)
    write(ws, "f.txt", "hi\n")
    r = call("git.commit", {"message": "it's a test"})
    assert r["exit_code"] == 0, r
    log = subprocess.run(["git", "log", "--format=%an <%ae>|%s"], cwd=ws,
                         capture_output=True, text=True).stdout.strip()
    assert log == "Otto <otto@local>|it's a test"
    assert call("git.status", {})["exit_code"] == 0
