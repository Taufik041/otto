import os, subprocess, base64

from shared import config

CAP = 10_000

def _run(cmd, timeout=60) -> dict:
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=config.WORKSPACE,
        capture_output=True,
        text=True,
        timeout=timeout
    )
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

    existing = _run(cmd=f"wc -c < {path} 2>/dev/null || echo 0")
    old_size = int(existing["stdout"].strip() or 0)
    new_size = len(content.encode())

    if old_size > 0 and new_size < old_size * 0.5:
        return {"exit_code": 1, "stdout": "",
                "stderr": (f"refusing to write: {path} is {old_size} bytes and the new content is "
                           f"only {new_size}. This looks like an accidental truncation. "
                           "Use fs_replace to modify an existing file.")}

    b64 = base64.b64encode(content.encode()).decode()
    w = _run(cmd=f"echo '{b64}' | base64 -d > {path}")
    if w["exit_code"] != 0:
        return w
    return {"exit_code": 0, "stdout": f"wrote {new_size} bytes to {path}", "stderr": ""}

def handle_code_search(payload) -> dict:
    pattern = payload["pattern"]
    r = _run(cmd=f"rg -n '{pattern}' | head -51")
    lines = r["stdout"].splitlines()
    truncated = len(lines) > 50
    out = "\n".join(lines[:50])
    if truncated:
        out += ("\n[... results truncated at 50 matches. This is NOT the total count. "
                "Use shell_exec with `rg -c` to count matches.]")
    return {"exit_code": r["exit_code"], "stdout": out, "stderr": r["stderr"]}

def handle_git_status(payload=None) -> dict:
    return _run(cmd = "git status")

def handle_git_diff(payload=None) -> dict:
    return _run(cmd = "git diff")

def handle_git_commit(payload) -> dict:
    message = payload["message"].replace("'", "'\\''")
    return _run(cmd=f"git add -A && git -c user.email=otto@local -c user.name=Otto commit -m '{message}'")

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


REGISTRY = {
    "shell.exec": handle_shell_exec,
    "fs.read": handle_fs_read,
    "fs.write": handle_fs_write,
    "code.search": handle_code_search,
    "git.status": handle_git_status,
    "git.diff": handle_git_diff,
    "git.commit": handle_git_commit,
    "fs.replace": handle_fs_replace,
}

