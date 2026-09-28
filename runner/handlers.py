import base64, json, os, subprocess
import urllib.error, urllib.parse, urllib.request

from shared import config
from shared.github import API, parse_repo

CAP = 10_000
SECRET_ENV = ("GITHUB_TOKEN",)
GITHUB_TIMEOUT = 30  # seconds per GitHub API request


def _child_env(extra=None) -> dict:
    # commands never inherit the token; git.push passes it per command instead
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env.update(extra or {})
    return env


def _run(cmd, timeout=60) -> dict:
    # shell=True on purpose: only shell.exec uses this
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=config.WORKSPACE,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=timeout
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout[:CAP],
        "stderr": result.stderr[:CAP]
        }


def _run_argv(argv, timeout=60, env=None) -> dict:
    # no shell: model text is passed as separate argv entries, never interpolated
    try:
        result = subprocess.run(
            argv,
            cwd=config.WORKSPACE,
            env=_child_env(env),
            stdin=subprocess.DEVNULL,  # rg would otherwise search an inherited stdin pipe
            capture_output=True,
            text=True,
            timeout=timeout
        )
    except FileNotFoundError as e:
        return {"exit_code": 127, "stdout": "", "stderr": str(e)}
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout[:CAP],
        "stderr": result.stderr[:CAP]
        }


def _resolve(path):
    ws = os.path.realpath(config.WORKSPACE)
    full = os.path.realpath(os.path.join(ws, path))

    # a plain startswith would let /workspace-evil through
    if os.path.commonpath([ws, full]) != ws:
        raise ValueError(f"Path escapes workspace: {path}")

    return full

def _read_text(path) -> str:
    # newline="" keeps \r\n etc. byte-for-byte
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _lines(text) -> list:
    # split on "\n" only, keeping it, like sed/wc do
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _io_error(path, e) -> dict:
    return {"exit_code": 1, "stdout": "", "stderr": f"cannot access {path}: {e}"}

def handle_shell_exec(payload) -> dict:
    return _run(payload["cmd"], payload.get("timeout", 60))

def handle_fs_read(payload) -> dict:
    path = _resolve(payload["path"])
    start = payload.get("start_line")
    end = payload.get("end_line")

    try:
        text = _read_text(path)
    except (OSError, UnicodeDecodeError) as e:
        return _io_error(path, e)

    if start is None:
        total = text.count("\n")  # same count as `wc -l`
        if total > 400:
            return {"exit_code": 1, "stdout": "",
                    "stderr": f"{path} has {total} lines; pass start_line/end_line"}
        start, end = 1, total

    start = int(start)
    end = int(end or start + 200)
    if start < 1:
        return {"exit_code": 1, "stdout": "", "stderr": f"start_line must be >= 1, got {start}"}
    # same slice as `sed -n 'start,endp'` (prints just line `start` when end < start)
    out = "".join(_lines(text)[start - 1:max(end, start)])
    return {"exit_code": 0, "stdout": out[:CAP], "stderr": ""}

def handle_fs_write(payload) -> dict:
    path = _resolve(payload["path"])
    content = payload["content"]

    try:
        old_size = os.path.getsize(path)
    except OSError:
        old_size = 0
    new_size = len(content.encode())

    if old_size > 0 and new_size < old_size * 0.5:
        return {"exit_code": 1, "stdout": "",
                "stderr": (f"refusing to write: {path} is {old_size} bytes and the new content is "
                           f"only {new_size}. This looks like an accidental truncation. "
                           "Use fs_replace to modify an existing file.")}

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_text(path, content)
    except OSError as e:
        return _io_error(path, e)
    return {"exit_code": 0, "stdout": f"wrote {new_size} bytes to {path}", "stderr": ""}

def handle_code_search(payload) -> dict:
    pattern = payload["pattern"]
    r = _run_argv(["rg", "-n", "--", pattern])
    if r["exit_code"] == 1:  # rg: no matches (the old `| head` pipeline reported 0)
        r["exit_code"] = 0
    lines = r["stdout"].splitlines()
    truncated = len(lines) > 50
    out = "\n".join(lines[:50])
    if truncated:
        out += ("\n[... results truncated at 50 matches. This is NOT the total count. "
                "Use shell_exec with `rg -c` to count matches.]")
    return {"exit_code": r["exit_code"], "stdout": out, "stderr": r["stderr"]}

def handle_git_status(payload=None) -> dict:
    return _run_argv(["git", "status"])

def handle_git_diff(payload=None) -> dict:
    return _run_argv(["git", "diff"])

def handle_git_commit(payload) -> dict:
    add = _run_argv(["git", "add", "-A"])
    if add["exit_code"] != 0:
        return add
    # the sandbox's entrypoint sets the repo's identity; fall back to Otto elsewhere
    has_identity = all(_run_argv(["git", "config", "--local", "--get", f"user.{k}"])["exit_code"] == 0
                       for k in ("name", "email"))
    identity = [] if has_identity else ["-c", "user.email=otto@local", "-c", "user.name=Otto"]
    commit = _run_argv(["git", *identity, "commit", "-m", payload["message"]])
    commit["stdout"] = (add["stdout"] + commit["stdout"])[:CAP]
    commit["stderr"] = (add["stderr"] + commit["stderr"])[:CAP]
    return commit

def handle_fs_replace(payload) -> dict:
    path = _resolve(payload["path"])
    old_str = payload["old_str"]
    new_str = payload["new_str"]

    try:
        content = _read_text(path)
    except (OSError, UnicodeDecodeError) as e:
        return _io_error(path, e)

    count = content.count(old_str)
    if count == 0:
        return {"exit_code": 1, "stdout": "",
                "stderr": f"old_str not found in {path}. It must match the file exactly, "
                          "including whitespace and indentation."}
    if count > 1:
        return {"exit_code": 1, "stdout": "",
                "stderr": f"old_str appears {count} times in {path}; "
                          "include surrounding lines to make it unique."}

    updated = content.replace(old_str, new_str)
    try:
        _write_text(path, updated)
    except OSError as e:
        return _io_error(path, e)
    return {"exit_code": 0, "stdout": f"replaced 1 occurrence in {path}", "stderr": ""}

def _current_branch():
    r = _run_argv(["git", "symbolic-ref", "--short", "-q", "HEAD"])
    return r["stdout"].strip() if r["exit_code"] == 0 else None


def _scrub(result, secrets) -> dict:
    out = dict(result)
    for k, v in out.items():
        if isinstance(v, str):
            for s in secrets:
                v = v.replace(s, "[REDACTED]")
            out[k] = v
    return out


def handle_git_push(payload=None) -> dict:
    branch = _current_branch()
    if not branch:
        return {"exit_code": 1, "stdout": "", "branch": None,
                "stderr": "not on a branch (detached HEAD); check out a branch before pushing"}
    token = config.GITHUB_TOKEN
    if not token:
        return {"exit_code": 1, "stdout": "", "branch": branch,
                "stderr": "cannot push: no GITHUB_TOKEN in the sandbox (the orchestrator injects one "
                          "when the GitHub App is configured)"}
    # the token rides on this one command's argv; it never lands in .git/config or the remote URL
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    r = _run_argv(["git", "-c", f"http.extraheader=AUTHORIZATION: basic {basic}",
                   "push", "-u", "origin", branch],
                  timeout=120, env={"GIT_TERMINAL_PROMPT": "0"})
    r = _scrub(r, [token, basic])
    r["branch"] = branch
    return r


def _error(stderr) -> dict:
    return {"exit_code": 1, "stdout": "", "stderr": stderr}


def _default_branch() -> str:
    r = _run_argv(["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
    ref = r["stdout"].strip()
    return ref.removeprefix("refs/remotes/origin/") if r["exit_code"] == 0 and ref else "main"


def _github(method, path, token, body=None):
    # stdlib only: the sandbox image has no requests
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": "otto"})
    with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
        return json.loads(resp.read() or b"null")


def _api_error(e: urllib.error.HTTPError) -> str:
    """'GitHub API 422: Validation Failed; A pull request already exists for ...'"""
    try:
        data = json.loads(e.read())
    except (ValueError, OSError):
        data = {}
    data = data if isinstance(data, dict) else {}
    parts = [data.get("message") or str(e.reason)]
    parts += [x.get("message") or x.get("code") for x in data.get("errors") or [] if isinstance(x, dict)]
    return f"GitHub API {e.code}: " + "; ".join(p for p in parts if p)


def handle_git_open_pr(payload) -> dict:
    token = config.GITHUB_TOKEN
    if not token:
        return _error("cannot open a PR: no GITHUB_TOKEN in the sandbox (the orchestrator injects one "
                      "when the GitHub App is configured)")
    try:
        owner, repo = parse_repo(config.REPO_URL)
    except ValueError as e:
        return _error(f"cannot open a PR: {e}")
    branch = _current_branch()
    if not branch:
        return _error("not on a branch (detached HEAD); check out and push a branch first")
    base = payload.get("base") or _default_branch()
    pulls = f"/repos/{owner}/{repo}/pulls"

    try:
        try:
            pr = _github("POST", pulls, token, {"title": payload["title"], "body": payload.get("body", ""),
                                                "head": branch, "base": base})
        except urllib.error.HTTPError as e:
            msg = _api_error(e)
            if e.code != 422 or "already exists" not in msg:
                return _scrub(_error(msg), [token])
            # a PR from this branch is already open (e.g. on resume): hand that one back
            query = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open"})
            prs = _github("GET", f"{pulls}?{query}", token)
            if not prs:
                return _scrub(_error(msg), [token])
            pr = prs[0]
    except urllib.error.HTTPError as e:
        return _scrub(_error(_api_error(e)), [token])
    except (urllib.error.URLError, OSError, ValueError) as e:  # timeouts are OSErrors
        return _scrub(_error(f"GitHub API request failed: {e}"), [token])

    return {"exit_code": 0, "stdout": pr["html_url"], "stderr": "",
            "number": pr["number"], "html_url": pr["html_url"]}


REGISTRY = {
    "shell.exec": handle_shell_exec,
    "fs.read": handle_fs_read,
    "fs.write": handle_fs_write,
    "code.search": handle_code_search,
    "git.status": handle_git_status,
    "git.diff": handle_git_diff,
    "git.commit": handle_git_commit,
    "fs.replace": handle_fs_replace,
    "git.push": handle_git_push,
    "git.open_pr": handle_git_open_pr,
}

