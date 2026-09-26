from openai import OpenAI
import sys, json, os
from step1_1 import run
from dotenv import load_dotenv
import base64

load_dotenv(override=True)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("API_KEY")
)

MODEL = "openrouter/free"

TOOLS = [
    { # shell_exec
        "type": "function", 
        "function": {
            "name": "shell_exec",
            "description": "Run a shell command in the repo at /workspace. Non interactive commands only",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"}
                },
                "required": ["cmd"]
            }
        }
    },
    { # fs_read
        "type": "function",
        "function": {
            "name": "fs_read",
            "description": "Read a slice of a file. Omit line numbers only for small files. end_line defaults to start_line + 200; call again with a later start_line to continue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"}
                },
                "required": ["path"]
            }
        }
    },
    { # fs_write
        "type": "function",
        "function": {
            "name": "fs_write",
            "description": "Write full file content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    },
    { # code_search
        "type": "function",
        "function": {
            "name": "code_search",
            "description": "ripgrep the repo, returns file:line matches",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"}
                },
                "required": ["pattern"]
            }
        }
    },
    { # git_status
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "git status",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    { # git_diff
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "git diff",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    { # git_commit
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "git add -A && commit",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                },
                "required": ["message"]
            }
        }
    },
]
def shell_exec(cmd: str) -> dict:
    return run(cmd=cmd)

def fs_read(path: str, start_line: int | None = None, end_line: int | None = None):
    if start_line is None:
        n = run(cmd=f"wc -l < {path}")
        total = int(n["stdout"].strip() or 0)
        if total > 400:
            return {"exit_code": 1, "stdout": "",
                    "stderr": f"{path} has {total} lines; pass start_line/end_line"}
        start_line, end_line = 1, total
    end_line = end_line or start_line + 200
    return run(cmd=f"sed -n '{start_line},{end_line}p' {path}")

def fs_write(path: str, content: str) -> dict:
    """Create a new file, or fully rewrite a small one."""
    existing = run(cmd=f"wc -c < {path} 2>/dev/null || echo 0")
    old_size = int(existing["stdout"].strip() or 0)
    new_size = len(content.encode())

    if old_size > 0 and new_size < old_size * 0.5:
        return {"exit_code": 1, "stdout": "",
                "stderr": (f"refusing to write: {path} is {old_size} bytes and the new content is "
                           f"only {new_size}. This looks like an accidental truncation. "
                           "Use fs_replace to modify an existing file.")}

    b64 = base64.b64encode(content.encode()).decode()
    w = run(cmd=f"echo '{b64}' | base64 -d > {path}")
    if w["exit_code"] != 0:
        return w
    return {"exit_code": 0, "stdout": f"wrote {new_size} bytes to {path}", "stderr": ""}

def code_search(pattern: str) -> dict:
    r = run(cmd=f"rg -n '{pattern}' | head -51")
    lines = r["stdout"].splitlines()
    truncated = len(lines) > 50
    out = "\n".join(lines[:50])
    if truncated:
        out += ("\n[... results truncated at 50 matches. This is NOT the total count. "
                "Use shell_exec with `rg -c` to count matches.]")
    return {"exit_code": r["exit_code"], "stdout": out, "stderr": r["stderr"]}

def git_status():
    return run(cmd = "git status")

def git_diff():
    return run(cmd = "git diff")

def git_commit(message: str):
    return run(cmd=f"git add -A && git -c user.email=otto@local -c user.name=Otto commit -m '{message}'")

def fs_replace(path: str, old_str: str, new_str: str) -> dict:
    """Replace exactly one occurrence of old_str with new_str."""
    r = run(cmd=f"cat {path}")
    if r["exit_code"] != 0:
        return r

    content = r["stdout"]
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
    b64 = base64.b64encode(updated.encode()).decode()
    w = run(cmd=f"echo '{b64}' | base64 -d > {path}")
    if w["exit_code"] != 0:
        return w
    return {"exit_code": 0, "stdout": f"replaced 1 occurrence in {path}", "stderr": ""}

REGISTRY = {
    "shell_exec": shell_exec,
    "fs_read": fs_read,
    "fs_write": fs_write,
    "code_search": code_search,
    "git_status": git_status,
    "git_diff": git_diff,
    "git_commit": git_commit,
    "fs_replace": fs_replace,
}

SYSTEM = (
    "You are Otto, an autonomous coding agent working in a git repo at /workspace.\n"
    "\n"
    "Finding code: use code_search to locate symbols, then fs_read with line ranges "
    "around the hits. Never read a whole file when a slice will do.\n"
    "\n"
    "Editing code: use fs_replace. fs_write is ONLY for creating new files — never "
    "rewrite a file you did not create, and never retype a file from memory.\n"
    "\n"
    "Read any relevant docs (README, docs/) before changing behaviour. Respect comments "
    "that say code is frozen or deprecated.\n"
    "\n"
    "After every edit you MUST run the tests with shell_exec (python -m pytest -q) and "
    "report the result. Do not finish while tests are failing.\n"
    "\n"
    "When the task is complete and tests pass, git_commit with a short message, then "
    "summarize what you changed."
)

def execute_task():
    task = " ".join(sys.argv[1:])
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]

    for step in range(20):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        m = resp.choices[0].message

        if not m.tool_calls:
            print(f"\n[otto] {m.content}")
            return

        if m.content:
            print(f"[thinking] {m.content}")

        tool_calls = [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in m.tool_calls]
        messages.append({
            "role": "assistant",
            "content": m.content,
            "tool_calls": tool_calls
        })

        for tc in m.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            name = tc.function.name
            fn = REGISTRY.get(name)
            if fn is None:
                result = {"exit_code": 1, "stdout": "",
                          "stderr": f"unknown tool {name!r}; available: {', '.join(REGISTRY)}"}
                print(f"[error] unknown tool {name!r}")
            else:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = fn(**args)
                except TypeError as e:
                    result = {"exit_code": 1, "stdout": "", "stderr": f"{e}; check parameter names"}
                except Exception as e:
                    result = {"exit_code": 1, "stdout": "", "stderr": str(e)}
            print(f"[exit {result['exit_code']}] {(result['stdout'] or result['stderr'])[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result)[:20000]})

    print("[stopped] iteration cap")

if __name__== "__main__":
    print(sys.argv[1:])
    resp = execute_task()