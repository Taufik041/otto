"""Pull request reviews: someone comments "@<app> review" on a pull request (or one is opened in a
repo with auto-review on), and Otto posts one code review on GitHub. No sandbox, no code run.

The gateway takes the request (gateway/reviews.py), reads the pull request and its diff, and
makes a chat of kind "review" holding it (review.requested); a brain worker asks the model
(brain/review.py) and stores the review (review.drafted); the gateway posts it on GitHub
(review.posted). This module is what they share: which files get reviewed (select_files), the
diff framed as untrusted data (frame), and the model's answer checked (parse_output,
check_comments). The pr_reviews row of each request is taken once (claim), so a webhook delivered
again never reviews or posts twice.

    review.requested  {repo, number, title, url, author, head, base, head_sha, trigger,
                       requested_by, additions, deletions, total_files, files: [{path, status,
                       additions, deletions, patch, partial?}], skipped: [{path, reason}],
                       truncated}
    review.drafted    {summary, comments: [{path, line, body, excerpt: [{line, text, added}]}],
                       dropped, usage: {prompt_tokens, completion_tokens}}
    review.posted     {review_id, url, comments}
    review.failed     {message}
"""
import json
import re

from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select, update

from shared.db import get_db
from shared.events import load_events
from shared.models import AutoReview, PrReview, utcnow

MAX_FILES = 40           # files reviewed, at most
DIFF_BUDGET = 60_000     # bytes of diff the model gets, all files together
MAX_COMMENTS = 10        # inline comments a review posts, at most
SUMMARY_MAX = 6_000      # characters of the summary
BODY_MAX = 2_000         # characters of one inline comment
EXCERPT_LINES = 3        # lines the chat shows for a comment, ending at its line
ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")  # who may ask for a review
LIMIT_TEXT = "Otto's daily limit is reached. Try again tomorrow."
EVENT_REQUESTED, EVENT_DRAFTED, EVENT_POSTED, EVENT_FAILED = (
    "review.requested", "review.drafted", "review.posted", "review.failed")

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# --- which files ----------------------------------------------------------------------------------

LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock",
             "poetry.lock", "pipfile.lock", "uv.lock", "pdm.lock", "cargo.lock", "gemfile.lock", "composer.lock",
             "go.sum", "mix.lock", "podfile.lock", "pubspec.lock", "packages.lock.json", "flake.lock"}
GENERATED = re.compile(r"(^|/)(dist|build|vendor|node_modules|__generated__|generated)/|"
                       r"(_pb2(_grpc)?\.pyi?|\.pb\.go|\.pb\.(cc|h)|\.generated\.\w+|\.g\.dart|\.snap)$", re.IGNORECASE)
MINIFIED = re.compile(r"\.min\.(js|css|mjs)$|\.(js|css)\.map$|\.map$", re.IGNORECASE)
BINARY = re.compile(r"\.(png|jpe?g|gif|bmp|ico|webp|avif|tiff?|psd|pdf|zip|gz|tgz|bz2|xz|7z|rar|jar|war|"
                    r"class|so|dylib|dll|exe|bin|o|a|wasm|woff2?|ttf|otf|eot|mp3|mp4|mov|avi|webm|ogg|wav|"
                    r"flac|sqlite3?|db|pyc|lockb)$", re.IGNORECASE)


def skip_reason(path, patch) -> str | None:
    """Why a changed file isn't reviewed ("lockfile", "generated", "minified", "binary"), or None.
    A file GitHub gives no patch for is binary (or too big to show)."""
    name = path.rsplit("/", 1)[-1].lower()
    if name in LOCKFILES or name.endswith(".lock"):
        return "lockfile"
    if MINIFIED.search(path):
        return "minified"
    if GENERATED.search(path):
        return "generated"
    if BINARY.search(path) or not patch:
        return "binary"
    return None


def _cut(patch, limit) -> str:
    """The patch's first whole lines within limit bytes."""
    out, used = [], 0
    for line in patch.split("\n"):
        size = len(line.encode()) + 1
        if used + size > limit:
            break
        out.append(line)
        used += size
    return "\n".join(out)


def select_files(files, max_files=MAX_FILES, budget=DIFF_BUDGET) -> dict:
    """The pull request's changed files (GitHub's GET .../pulls/{n}/files, in order) cut down to
    what the model gets: lockfiles, generated, minified and binary files are skipped; then the
    first max_files files within budget bytes of patch (the file that crosses it is cut at a line,
    and marked partial). {files, skipped, truncated}: truncated, some files (or part of one) were
    left out for the caps."""
    kept, skipped, used, truncated = [], [], 0, False
    for f in files:
        path, patch = f.get("filename") or "", f.get("patch") or ""
        if reason := skip_reason(path, patch):
            skipped.append({"path": path, "reason": reason})
            continue
        if truncated or len(kept) >= max_files:  # past a cap: the rest isn't reviewed
            truncated = True
            continue
        entry = {"path": path, "status": f.get("status") or "modified", "additions": f.get("additions") or 0,
                 "deletions": f.get("deletions") or 0, "patch": patch}
        if used + len(patch.encode()) > budget:
            entry["patch"], entry["partial"], truncated = _cut(patch, budget - used), True, True
            if not HUNK.match(entry["patch"]) or "\n" not in entry["patch"]:  # not even one line of it
                continue
        used += len(entry["patch"].encode())
        kept.append(entry)
    return {"files": kept, "skipped": skipped, "truncated": truncated}


# --- the diff's lines ---------------------------------------------------------------------------------

def numbered(patch):
    """Each line of a patch as (right-side line number or None, sign, text): sign is "+", " ",
    "-", "@" (a hunk header) or "\\" (no newline at end of file)."""
    n = None
    for line in patch.split("\n"):
        if m := HUNK.match(line):
            n = int(m.group(1))
            yield None, "@", line
        elif n is None or line.startswith("\\"):
            yield None, "\\", line
        elif line.startswith("-"):
            yield None, "-", line[1:]
        else:
            sign = "+" if line.startswith("+") else " "
            yield n, sign, line[1:]
            n += 1


def right_lines(patch) -> set[int]:
    """The lines of the new file a review comment may sit on: added and context lines."""
    return {n for n, _, _ in numbered(patch) if n is not None}


def excerpt(patch, line, size=EXCERPT_LINES) -> list[dict]:
    """The right side's lines up to line (at most size of them, from its hunk): {line, text, added}."""
    hunk = []
    for n, sign, text in numbered(patch):
        if sign == "@":
            hunk = []
        elif n is not None:
            hunk.append({"line": n, "text": text, "added": sign == "+"})
            if n == line:
                return hunk[-size:]
    return []


# --- the model's input, framed ---------------------------------------------------------------------

TAG = re.compile(r"<\s*(/?)\s*untrusted", re.IGNORECASE)


def inert(text) -> str:
    """Text that can't open or close the <untrusted> block it sits in."""
    return TAG.sub(lambda m: "&lt;" + m.group(1) + "untrusted", str(text or ""))


def _attr(v) -> str:
    return inert(str(v or "").replace("&", "&amp;").replace('"', "&quot;").replace("\n", " "))


def _numbered_patch(patch) -> str:
    """The patch with each right-side line's number in front, so the model can name lines."""
    out = []
    for n, sign, text in numbered(patch):
        out.append(text if sign in "@\\" else f"{'' if n is None else n:>6} {sign}{text}")
    return "\n".join(out)


def frame(req, comment=None) -> str:
    """The pull request (title, body, diff) and the comment that asked, as one <untrusted> block:
    nothing inside it can end it early."""
    head = (f'<untrusted kind="pull-request" repo="{_attr(req["repo"])}" number="{int(req["number"])}" '
            f'author="{_attr(req.get("author"))}" base="{_attr(req.get("base"))}" head="{_attr(req.get("head"))}">')
    parts = [head, f"Title: {inert(req.get('title'))}", "", "Description:", inert(req.get("body")) or "(none)"]
    if comment:
        parts += ["", "The comment that asked for this review:", inert(comment)]
    for f in req["files"]:
        partial = " (cut short: only its first part is shown)" if f.get("partial") else ""
        parts += ["", f"=== {inert(f['path'])} ({f['status']}, +{f['additions']} -{f['deletions']}){partial} ===",
                  inert(_numbered_patch(f["patch"]))]
    parts.append("</untrusted>")
    return "\n".join(parts)


# --- the model's answer ----------------------------------------------------------------------------

FENCE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _json(text):
    text = str(text or "").strip()
    if m := FENCE.match(text):
        text = m.group(1)
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                return None
    return None


def parse_output(text) -> tuple[dict | None, str | None]:
    """The model's review, checked: ({summary, comments: [{path, line, body}]}, None), or (None,
    why it isn't one). More than MAX_COMMENTS comments keep the first ones; long text is cut."""
    data = _json(text)
    if not isinstance(data, dict):
        return None, "not a JSON object"
    summary, comments = data.get("summary"), data.get("comments", [])
    if not isinstance(summary, str) or not summary.strip():
        return None, "summary must be a non-empty string"
    if not isinstance(comments, list):
        return None, "comments must be a list"
    out = []
    for c in comments:
        if not isinstance(c, dict):
            return None, "each comment must be an object"
        path, line, body = c.get("path"), c.get("line"), c.get("body")
        if not isinstance(path, str) or not path or isinstance(line, bool) or not isinstance(line, int) \
                or not isinstance(body, str) or not body.strip():
            return None, "each comment needs path (string), line (integer) and body (string)"
        out.append({"path": path, "line": line, "body": body.strip()[:BODY_MAX]})
    return {"summary": summary.strip()[:SUMMARY_MAX], "comments": out[:MAX_COMMENTS]}, None


def summary_of(text) -> str | None:
    """A summary to post when the model's answer never became a valid review: its JSON "summary"
    if it has one. Never its raw text: an answer that isn't the JSON asked for may not be a review
    at all, and it would go on GitHub."""
    data = _json(text)
    if isinstance(data, dict) and isinstance(data.get("summary"), str) and data["summary"].strip():
        return data["summary"].strip()[:SUMMARY_MAX]
    return None


def check_comments(comments, files) -> tuple[list[dict], int]:
    """The comments that sit on the diff: a reviewed file's path, and an added or context line of
    its right side. Each kept one gets its excerpt. (kept, how many were dropped)."""
    patches = {f["path"]: f["patch"] for f in files}
    kept = []
    for c in comments:
        patch = patches.get(c["path"])
        if patch is None or c["line"] not in right_lines(patch):
            continue
        kept.append({**c, "excerpt": excerpt(patch, c["line"])})
    return kept, len(comments) - len(kept)


def as_text(drafted) -> str:
    """The review as the chat's model sees it in follow-ups."""
    parts = [drafted["summary"]]
    for c in drafted["comments"]:
        parts += ["", f"**{c['path']}:{c['line']}**: {c['body']}"]
    return "\n".join(parts)


def caps_note(req) -> str:
    """What the summary says about files the review left out, or ""."""
    notes = []
    if req.get("truncated"):
        n = len(req["files"])
        notes.append(f"Otto reviewed the first part of this pull request ({n} of its files, about "
                     f"{DIFF_BUDGET // 1000} KB of the diff at most); the rest wasn't reviewed.")
    if skipped := req.get("skipped"):
        notes.append(f"Skipped {len(skipped)} {'file' if len(skipped) == 1 else 'files'} "
                     "(lockfiles, generated, minified or binary).")
    return " ".join(notes)


def latest(sid, type) -> dict | None:
    """The chat's latest event of this type's payload (review.requested, review.drafted, ...)."""
    return next((e.payload for e in reversed(load_events(sid)) if e.type == type), None)


# --- requests, taken once ---------------------------------------------------------------------------

def claim(key, user_id, repo, number, trigger, comment_id=None) -> bool:
    """Take the review request key: False if it was taken already (a webhook delivered again)."""
    try:
        with get_db() as s:
            s.add(PrReview(key=key, user_id=user_id, repo=repo, number=number, trigger=trigger,
                           comment_id=comment_id))
        return True
    except IntegrityError:
        return False


def get(key) -> PrReview | None:
    with get_db() as s:
        return s.get(PrReview, key)


def for_session(sid) -> PrReview | None:
    with get_db() as s:
        return s.exec(select(PrReview).where(PrReview.session_id == sid)).first()


def move(key, state, allowed_from=None, **fields) -> bool:
    """Set the request's state (only from one of allowed_from, if given), and fields. True if it moved."""
    q = update(PrReview).where(PrReview.key == key)
    if allowed_from is not None:
        q = q.where(PrReview.state.in_(allowed_from))
    with get_db() as s:
        return s.exec(q.values(state=state, updated_at=utcnow(), **fields)).rowcount == 1


# --- auto-review settings ---------------------------------------------------------------------------

def auto_review(repo) -> AutoReview | None:
    """The repo's auto-review setting ("owner/name", any case), or None while it's off."""
    with get_db() as s:
        return s.get(AutoReview, (repo or "").lower())


def auto_reviews(repos) -> dict[str, AutoReview]:
    """The settings of the repos that have auto-review on, by lower-cased full name."""
    keys = [r.lower() for r in repos]
    if not keys:
        return {}
    with get_db() as s:
        return {r.repo_key: r for r in s.exec(select(AutoReview).where(AutoReview.repo_key.in_(keys))).all()}


def set_auto_review(repo, user_id, enabled) -> AutoReview | None:
    """Turn auto-review on (by user_id, who then pays for its reviews) or off."""
    key = repo.lower()
    with get_db() as s:
        s.exec(delete(AutoReview).where(AutoReview.repo_key == key))
        if not enabled:
            return None
        row = AutoReview(repo_key=key, full_name=repo, user_id=user_id)
        s.add(row)
    return auto_review(repo)
