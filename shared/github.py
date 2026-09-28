import re

API = "https://api.github.com"

# https://[creds@]github.com/owner/repo[.git][/], git@github.com:owner/repo[.git], ssh://git@github.com/owner/repo
_REPO = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


def parse_repo(url) -> tuple[str, str]:
    """(owner, repo) from a GitHub repo URL; raises ValueError for anything else."""
    m = _REPO.match((url or "").strip())
    if not m:
        raise ValueError(f"not a GitHub repo URL: {url!r}")
    return m["owner"], m["repo"]
