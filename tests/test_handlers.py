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


def big_text():
    # ~30k chars, well past the 10k output cap, with unique lines
    return "".join(f"line {i:05d} some padding text here\n" for i in range(1, 900))


def test_fs_replace_large_file_keeps_every_byte(ws):
    text = big_text()
    assert len(text) > 30_000
    p = write(ws, "big.txt", text)
    r = call("fs.replace", {"path": "big.txt", "old_str": "line 00500 ", "new_str": "LINE-500 "})
    assert r["exit_code"] == 0, r
    assert open(p).read() == text.replace("line 00500 ", "LINE-500 ")


def test_fs_replace_finds_match_past_10k(ws):
    write(ws, "big.txt", big_text())
    r = call("fs.replace", {"path": "big.txt", "old_str": "line 00890 ", "new_str": "x "})
    assert r["exit_code"] == 0, r


def test_fs_replace_preserves_crlf(ws):
    p = os.path.join(ws, "crlf.txt")
    with open(p, "wb") as f:
        f.write(b"a\r\nb\r\n")
    call("fs.replace", {"path": "crlf.txt", "old_str": "b", "new_str": "c"})
    assert open(p, "rb").read() == b"a\r\nc\r\n"


def test_fs_read_range_past_10k(ws):
    write(ws, "big.txt", big_text())
    r = call("fs.read", {"path": "big.txt", "start_line": 850, "end_line": 851})
    assert r["stdout"] == "line 00850 some padding text here\nline 00851 some padding text here\n"


def test_fs_read_output_capped_at_10k(ws):
    write(ws, "big.txt", big_text())
    r = call("fs.read", {"path": "big.txt", "start_line": 1, "end_line": 399})
    assert r["exit_code"] == 0
    assert len(r["stdout"]) == 10_000


def test_fs_read_missing_file_errors():
    r = call("fs.read", {"path": "nope.txt"})
    assert r["exit_code"] != 0
    assert "nope.txt" in r["stderr"]


def test_fs_replace_missing_file_errors():
    r = call("fs.replace", {"path": "nope.txt", "old_str": "a", "new_str": "b"})
    assert r["exit_code"] != 0
    assert "nope.txt" in r["stderr"]


def test_resolve_rejects_sibling_with_same_prefix(ws):
    # e.g. /workspace-evil must not pass for workspace /workspace
    evil = ws + "-evil"
    os.makedirs(evil, exist_ok=True)
    with pytest.raises(ValueError, match="escapes workspace"):
        _resolve(f"../{os.path.basename(evil)}/secret.txt")


def test_resolve_rejects_absolute_path_outside():
    with pytest.raises(ValueError, match="escapes workspace"):
        _resolve("/etc/passwd")


def test_resolve_allows_workspace_itself(ws):
    assert _resolve(".") == ws


def test_resolve_tolerates_trailing_slash_in_workspace(ws, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE", ws + "/")
    assert _resolve("a.txt") == os.path.join(ws, "a.txt")


def test_fs_write_path_with_space_creates_parent_dirs(ws):
    r = call("fs.write", {"path": "my dir/sub dir/new file.txt", "content": "hi\n"})
    assert r["exit_code"] == 0, r
    assert open(os.path.join(ws, "my dir", "sub dir", "new file.txt")).read() == "hi\n"


def test_fs_write_shrink_guard_path_with_space(ws):
    p = write(ws, "a file.txt", "x" * 100)
    r = call("fs.write", {"path": "a file.txt", "content": "y"})
    assert r["exit_code"] == 1
    assert "is 100 bytes" in r["stderr"]
    assert open(p).read() == "x" * 100


def test_fs_write_error_is_returned_not_raised(ws):
    write(ws, "afile", "x")
    r = call("fs.write", {"path": "afile/child.txt", "content": "hi"})
    assert r["exit_code"] != 0
    assert r["stderr"]


def test_fs_read_and_replace_path_with_space(ws):
    p = write(ws, "a file.txt", "one\ntwo\n")
    assert call("fs.read", {"path": "a file.txt"})["stdout"] == "one\ntwo\n"
    assert call("fs.replace", {"path": "a file.txt", "old_str": "two", "new_str": "2"})["exit_code"] == 0
    assert open(p).read() == "one\n2\n"


def test_non_shell_handlers_never_use_a_shell(ws, monkeypatch):
    seen = []
    real_run = subprocess.run

    def spy(cmd, *a, **kw):
        seen.append((cmd, kw.get("shell", False)))
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(handlers.subprocess, "run", spy)
    subprocess.run(["git", "init", "-q", ws], check=True)
    write(ws, "f.txt", "it's here\n")
    call("fs.write", {"path": "g.txt", "content": "x"})
    call("fs.read", {"path": "f.txt"})
    call("fs.replace", {"path": "f.txt", "old_str": "here", "new_str": "there"})
    call("code.search", {"pattern": "it's"})
    call("git.status", {})
    call("git.diff", {})
    call("git.commit", {"message": "m"})
    assert seen, "expected subprocess calls"
    for cmd, shell in seen:
        assert isinstance(cmd, list) and not shell, cmd
    assert ["rg", "-n", "--", "it's"] in [c for c, _ in seen]


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
def test_code_search_pattern_with_quote(ws):
    write(ws, "f.txt", "nothing\nit's here\n")
    r = call("code.search", {"pattern": "it's"})
    assert r["exit_code"] == 0, r
    assert r["stdout"] == "f.txt:2:it's here"


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
def test_code_search_no_matches_is_not_an_error(ws):
    write(ws, "f.txt", "nothing\n")
    r = call("code.search", {"pattern": "zzz"})
    assert r["exit_code"] == 0
    assert r["stdout"] == ""


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
def test_code_search_pattern_starting_with_dash(ws):
    write(ws, "f.txt", "a -v flag\n")
    r = call("code.search", {"pattern": "-v"})
    assert r["stdout"] == "f.txt:1:a -v flag"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_commit_message_is_not_shell_expanded(ws):
    subprocess.run(["git", "init", "-q", ws], check=True)
    write(ws, "f.txt", "hi\n")
    msg = "it's $(touch pwned) `id` \"q\""
    assert call("git.commit", {"message": msg})["exit_code"] == 0
    log = subprocess.run(["git", "log", "--format=%s"], cwd=ws, capture_output=True, text=True).stdout
    assert log.strip() == msg
    assert not os.path.exists(os.path.join(ws, "pwned"))


# --- what the UI shows of an edit: a unified diff, lossless, relative to the workspace ----------

def test_fs_replace_returns_a_unified_diff(ws):
    os.makedirs(os.path.join(ws, "src"))
    write(ws, "src/p.py", "".join(f"l{i}\n" for i in range(1, 11)))
    r = call("fs.replace", {"path": "src/p.py", "old_str": "l5\n", "new_str": "L5\nL5b\n"})
    assert r["exit_code"] == 0
    assert r["diff"] == ("--- a/src/p.py\n+++ b/src/p.py\n@@ -2,7 +2,8 @@\n"
                         " l2\n l3\n l4\n-l5\n+L5\n+L5b\n l6\n l7\n l8\n")
    assert (r["added"], r["removed"]) == (2, 1)


def test_fs_replace_diff_of_an_absolute_workspace_path(ws):
    write(ws, "f.txt", "a = 1\n")
    r = call("fs.replace", {"path": os.path.join(ws, "f.txt"), "old_str": "1", "new_str": "2"})
    assert r["diff"].startswith("--- a/f.txt\n+++ b/f.txt\n")


def test_fs_replace_diff_marks_a_missing_final_newline(ws):
    write(ws, "f.txt", "a\nb")
    r = call("fs.replace", {"path": "f.txt", "old_str": "b", "new_str": "c"})
    assert r["diff"].endswith("-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n")


def test_fs_write_new_file_diff(ws):
    r = call("fs.write", {"path": "n.txt", "content": "x\ny\n"})
    assert r["created"] is True
    assert r["diff"] == "--- /dev/null\n+++ b/n.txt\n@@ -0,0 +1,2 @@\n+x\n+y\n"
    assert (r["added"], r["removed"]) == (2, 0)


def test_fs_write_overwrite_diff(ws):
    write(ws, "f.txt", "a\nb\n")
    r = call("fs.write", {"path": "f.txt", "content": "a\nc\n"})
    assert r["created"] is False
    assert (r["added"], r["removed"]) == (1, 1)
    assert "-b\n+c\n" in r["diff"]


def test_diff_is_capped_on_a_line_boundary(ws):
    big = "".join(f"line {i}\n" for i in range(5000))
    r = call("fs.write", {"path": "big.txt", "content": big})
    assert len(r["diff"]) <= 10_000 and r["diff"].endswith("\n") and r["diff_truncated"] is True
    assert r["added"] == 5000  # the counts are of the whole change


def test_failed_edits_carry_no_diff(ws):
    write(ws, "f.txt", "a\n")
    r = call("fs.replace", {"path": "f.txt", "old_str": "zzz", "new_str": "y"})
    assert "diff" not in r
