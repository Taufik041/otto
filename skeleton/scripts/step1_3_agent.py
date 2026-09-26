from openai import OpenAI
import sys, json, os, uuid
from dotenv import load_dotenv
import base64, asyncio
from aio_pika import Message, connect

load_dotenv(override=True)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("API_KEY")
)

MODEL = "openrouter/free"
SID = os.environ.get("SESSION_ID", "s1")

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
    { # fs_replace
        "type": "function",
        "function": {
            "name": "fs_replace",
            "description": ("Replace an exact string in a file. Preferred over fs_write for edits. "
                            "old_str must appear exactly once, matching whitespace exactly — "
                            "include surrounding lines if needed for uniqueness."),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_str": {"type": "string"},
                    "new_str": {"type": "string"}
                },
                "required": ["path", "old_str", "new_str"]
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

KIND = {
    "shell_exec": "shell.exec",
    "fs_read": "fs.read",
    "fs_write": "fs.write",
    "code_search": "code.search",
    "git_status": "git.status",
    "git_diff": "git.diff",
    "git_commit": "git.commit",
    "fs_replace": "fs.replace",    
}


async def bus_call(ch, results, kind, payload) -> dict:
    aid = str(uuid.uuid4())
    action = {
        "session_id": SID,
        "action_id": aid,
        "kind": kind,
        "payload": payload
    }
    await ch.default_exchange.publish(
        Message(json.dumps(action).encode()),
        routing_key=f"otto.{SID}.actions"
    )
    async with results.iterator() as it:
        async for msg in it:
            async with msg.process():
                r = json.loads(msg.body)
                if r.get("action_id") == aid:
                    return r["payload"]

    return {}

async def execute_task(ch, results):
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
            name = tc.function.name
            kind = KIND.get(name)
            result = {}
            if not kind:
                result = {
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": f"unknown tool {name!r}; available: {', '.join(KIND)}"
                }
                print(f"[error] unknown tool {name!r}")
            else:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = await bus_call(ch, results, kind, args)
                except Exception as e:
                    result = {"exit_code": 1, "stdout": "", "stderr": str(e)}
            print(f"[exit {result.get('exit_code')}] {(result.get('stdout') or result.get('stderr') or '')[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result)[:20000]})
                

    print("[stopped] iteration cap")


async def main():
    conn = await connect("amqp://guest:guest@localhost/")
    ch = await conn.channel()
    await ch.declare_queue(f"otto.{SID}.actions", durable=True)
    results = await ch.declare_queue(f"otto.{SID}.results", durable=True)
    await execute_task(ch, results)
    await conn.close()

if __name__== "__main__":
    asyncio.run(main())