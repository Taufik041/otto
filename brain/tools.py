SYSTEM = (
    "You are Otto, an autonomous coding agent working in a git repo at /workspace.\n"
    "\n"
    "Stay within the task. If unrelated tests fail, mention them in your summary instead of fixing them.\n"
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
    "When the task is done and the tests pass, you MUST git_commit with a short message, then "
    "git_push. Do not open a pull request: the user decides whether to open a pull request. "
    "Then write your final summary: the root cause, the fix and the test results (it becomes "
    "the pull request's description if the user opens one). Never end a task that changed "
    "files without committing and pushing."
)

CHAT_SYSTEM = (
    "You are Otto, a helpful assistant for software work. In this chat you have no tools and no "
    "access to any repository: answer from what the user tells you, and never claim to have run, "
    "read or changed anything.\n"
    "\n"
    "When a request needs code changes (or reading a repo's code), say you can do it if they mention "
    "the repo with @ (for example @owner/repo): you then work on it in a sandbox, run the tests and "
    "open a pull request."
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
    { # git_push
        "type": "function",
        "function": {
            "name": "git_push",
            "description": "Push the current branch (this session's otto/<id> branch) to origin",
            "parameters": {
                "type": "object",
                "properties": {}
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
    "git_push": "git.push",
}

PARAMETERS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}


def missing_args(name, args) -> str | None:
    """A message the model can act on if args lack a required parameter of tool `name`, else None."""
    schema = PARAMETERS[name]
    missing = [p for p in schema.get("required", []) if p not in args]
    if not missing:
        return None
    return (f"missing required parameter(s): {', '.join(missing)}. "
            f"{name} takes: {', '.join(schema['properties'])}")
