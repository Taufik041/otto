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
    "summarize what you changed.\n"
    "\n"
    "After committing with tests passing, call git_push, then git_open_pr with a clear title "
    "and a body explaining the root cause, the fix, and the test results. If a PR already "
    "exists for this branch, just push: the new commits land on it."
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
    { # git_open_pr
        "type": "function",
        "function": {
            "name": "git_open_pr",
            "description": ("Open a pull request from the pushed current branch. Returns the existing PR "
                            "if one is already open for this branch."),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string", "description": "root cause, fix, and test results"},
                    "base": {"type": "string", "description": "target branch; omit to use the repo's default branch"}
                },
                "required": ["title", "body"]
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
    "git_open_pr": "git.open_pr",
}
