#!/bin/sh
set -e

# 1. Clone the repo into /workspace if given and not already present.
if [ -n "$REPO_URL" ] && [ ! -d /workspace/.git ]; then
    if [ -n "$GITHUB_TOKEN" ]; then
        AUTH_URL=$(echo "$REPO_URL" | sed "s#https://#https://x-access-token:${GITHUB_TOKEN}@#")
        git clone "$AUTH_URL" /workspace
    else
        git clone "$REPO_URL" /workspace
    fi
fi

# 2. Install repo deps into otto's user space (non-root safe), best-effort.
if [ -f /workspace/pyproject.toml ] || [ -f /workspace/setup.py ]; then
    pip install --user -e /workspace 2>/dev/null || true
fi

# 3. Hand off to the runner (replaces this shell as PID 1).
exec python /app/runner.py