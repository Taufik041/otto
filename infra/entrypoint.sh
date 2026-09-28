#!/bin/sh
set -e

# git in /workspace, authenticated for this one command only (the token never goes into the config)
git_auth() {
    if [ -n "$GITHUB_TOKEN" ]; then
        basic=$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 | tr -d '\n')
        git -C /workspace -c "http.extraheader=AUTHORIZATION: basic $basic" "$@"
    else
        git -C /workspace "$@"
    fi
}

# 1. Clone the repo into /workspace if given and not already present, onto the session's branch.
if [ -n "$REPO_URL" ] && [ ! -d /workspace/.git ]; then
    if [ -n "$GITHUB_TOKEN" ]; then
        AUTH_URL=$(echo "$REPO_URL" | sed "s#https://#https://x-access-token:${GITHUB_TOKEN}@#")
        git clone "$AUTH_URL" /workspace
        # drop the token from .git/config right away, where the model could read it
        git -C /workspace remote set-url origin "$REPO_URL"
    else
        git clone "$REPO_URL" /workspace
    fi

    # one branch per session: resume continues otto/$SESSION_ID if it was pushed before
    BRANCH="otto/$SESSION_ID"
    if git_auth fetch origin "$BRANCH" 2>/dev/null; then
        git -C /workspace checkout -b "$BRANCH" --track "origin/$BRANCH"
        echo "[entrypoint] resuming on $BRANCH"
    else
        git -C /workspace checkout -b "$BRANCH"
        echo "[entrypoint] new branch $BRANCH"
    fi

    git -C /workspace config user.name "ottoci[bot]"
    git -C /workspace config user.email "ottoci[bot]@users.noreply.github.com"
fi

# 2. Install repo deps into otto's user space (non-root safe), best-effort.
if [ -f /workspace/pyproject.toml ] || [ -f /workspace/setup.py ]; then
    pip install --user -e /workspace 2>/dev/null || true
fi

# 3. Hand off to the runner (replaces this shell as PID 1).
exec python -m runner.main
