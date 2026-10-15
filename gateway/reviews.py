"""Pull request reviews on GitHub (shared/review.py has the whole flow). The gateway's part: every
GitHub call, with the App's installation token.

- **Asking.** POST /github/webhook (gateway/ci.py) takes issue_comment and pull_request
  deliveries; normalize() keeps "@<slug> review" in a new comment on a pull request (not from a
  bot, our own App included) and, for auto-review, a pull request opened or marked ready for review
  (not a draft, and not one Otto's own App opened: a mention still reviews those). Those go on
  otto.reviews; the answer is a 202 at once.
- **Taking a request** (take, on the otto.reviews consumer). A mention counts only from the
  repo's OWNER, a MEMBER or a COLLABORATOR whose GitHub account is linked to an Otto account that
  has the repo in its installations; auto-review, from the user who turned it on. Anything else is
  ignored, and logged, never answered. The request is claimed once (pr_reviews), so a redelivery
  does nothing. Then: 👀 on the comment (only with OTTO_REVIEW_REACTION on, as it needs the
  App's Issues permission at Read and write; a refusal is logged and that's all), the daily limit (one
  short comment when it's used up), the pull request and its diff (cut down: review.select_files),
  and a chat of kind "review" holding them, queued for a brain worker (a "review" job).
- **Posting** (post, when the brain says "drafted"). One review, event COMMENT (never APPROVE or
  REQUEST_CHANGES): the summary, and the inline comments that sit on the diff. A request posts at
  most once: it moves to "posting" first, atomically; never from "posted"; and each review's body
  carries a hidden marker with the request's key, which is looked for on GitHub before posting
  (a post that went through but was recorded as failed, a timeout say, is found, not repeated).
"""
import asyncio, json, re, uuid

import requests
from aio_pika import DeliveryMode, Message
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from gateway import auth, github_app
from shared import config, review, usage
from shared.bus import SESSIONS_QUEUE, review_job
from shared.db import get_db
from shared.events import append_event, load_events
from shared.models import User
from shared.sessions import create_session, transition

EVENTS = ("issue_comment", "pull_request")
AUTO_ACTIONS = ("opened", "ready_for_review")  # not "synchronize": one review per pull request
COMMENT_MAX = 2_000  # characters of the asking comment the model gets
FILE_PAGES = 3       # pages of GitHub's changed files read (100 each), at most
TITLE = "Review: {title}"

router = APIRouter()


def log(text):
    print(f"[review] {text}", flush=True)


# --- the webhook's part ------------------------------------------------------------------------------

def mention(slug) -> re.Pattern | None:
    """"@<slug> review" as whole words, any case."""
    if not slug:
        return None
    return re.compile(rf"(?<![\w@/-])@{re.escape(slug)}\s+review(?![\w-])", re.I)


def asks_for_review(body, slug) -> bool:
    pattern = mention(slug)
    return bool(pattern and isinstance(body, str) and pattern.search(body))


def is_bot(user, via, slug) -> bool:
    """A comment from a bot: GitHub says so, the login ends in [bot], or our own App wrote it."""
    user = user or {}
    login = str(user.get("login") or "").lower()
    ours = bool(slug) and ((via or {}).get("slug") == slug or login == f"{slug.lower()}[bot]")
    return user.get("type") == "Bot" or login.endswith("[bot]") or ours


def normalize(event, p) -> dict | None:
    """A review request from a delivery: {type: "mention", repo, number, comment_id, author_id,
    author_login, association, comment} or {type: "auto", repo, number, head_sha}. None (and a
    line in the log) for anything else."""
    repo = (p.get("repository") or {}).get("full_name")
    if not isinstance(repo, str) or not repo:
        return None
    slug = config.GITHUB_APP_SLUG
    if event == "issue_comment":
        c, issue = p.get("comment") or {}, p.get("issue") or {}
        if p.get("action") != "created" or not issue.get("pull_request") or not asks_for_review(c.get("body"), slug):
            return None
        where = f"comment {c.get('id')} on {repo}#{issue.get('number')}"
        if is_bot(c.get("user"), c.get("performed_via_github_app"), slug):
            log(f"ignored {where}: written by a bot")
            return None
        user = c.get("user") or {}
        if not isinstance(c.get("id"), int) or not isinstance(issue.get("number"), int) or not isinstance(user.get("id"), int):
            return None
        return {"type": "mention", "repo": repo, "number": issue["number"], "comment_id": c["id"],
                "author_id": user["id"], "author_login": user.get("login") or "",
                "association": c.get("author_association") or "NONE", "comment": (c.get("body") or "")[:COMMENT_MAX]}
    if event == "pull_request":
        pr = p.get("pull_request") or {}
        if p.get("action") not in AUTO_ACTIONS or not isinstance(pr.get("number"), int):
            return None
        if pr.get("draft"):
            log(f"ignored {repo}#{pr['number']} ({p.get('action')}): a draft")
            return None
        if slug and str((pr.get("user") or {}).get("login") or "").lower() == f"{slug.lower()}[bot]":
            log(f"ignored {repo}#{pr['number']} ({p.get('action')}): opened by Otto's own App")
            return None
        return {"type": "auto", "repo": repo, "number": pr["number"], "head_sha": (pr.get("head") or {}).get("sha") or ""}
    return None


# --- GitHub calls --------------------------------------------------------------------------------------

def _send(method, url, token, **kw) -> requests.Response:
    try:
        return github_app.request(method, url, headers=github_app._headers(token), **kw)
    except requests.RequestException as e:
        raise github_app.GitHubError(f"{method} {url}: {type(e).__name__}") from None


def react(installation_id, repo, comment_id) -> bool:
    """👀 on the comment. False (logged) if GitHub refuses, e.g. without the permission."""
    token = github_app.installation_token(installation_id)
    try:
        r = _send("POST", f"{github_app.API}/repos/{repo}/issues/comments/{comment_id}/reactions", token,
                  json={"content": "eyes"})
    except github_app.GitHubError as e:
        log(f"no 👀 on comment {comment_id} in {repo}: {e}")
        return False
    if r.status_code >= 400:
        log(f"no 👀 on comment {comment_id} in {repo}: HTTP {r.status_code} (the App's permissions?)")
        return False
    return True


def comment(installation_id, repo, number, body) -> bool:
    """A comment on the pull request. False (logged) if GitHub refuses."""
    token = github_app.installation_token(installation_id)
    try:
        r = _send("POST", f"{github_app.API}/repos/{repo}/issues/{number}/comments", token, json={"body": body})
    except github_app.GitHubError as e:
        log(f"couldn't comment on {repo}#{number}: {e}")
        return False
    if r.status_code >= 400:
        log(f"couldn't comment on {repo}#{number}: HTTP {r.status_code}")
        return False
    return True


def pull(installation_id, repo, number) -> dict:
    token = github_app.installation_token(installation_id)
    return github_app._json("GET", f"{github_app.API}/repos/{repo}/pulls/{number}", headers=github_app._headers(token))


def pull_files(installation_id, repo, number) -> list[dict]:
    """The pull request's changed files, in GitHub's order (FILE_PAGES pages at most)."""
    token = github_app.installation_token(installation_id)
    url, params, files = f"{github_app.API}/repos/{repo}/pulls/{number}/files", {"per_page": 100}, []
    for _ in range(FILE_PAGES):
        r = github_app._call("GET", url, headers=github_app._headers(token), params=params)
        files += r.json()
        url, params = r.links.get("next", {}).get("url"), None
        if not url:
            break
    return files


def marker(key) -> str:
    """Hidden in a review's body (an HTML comment): which request it answers."""
    return f"<!-- otto-review:{key} -->"


def posted_review(installation_id, repo, number, key) -> dict | None:
    """The review already on GitHub for this request (its body has the marker), or None."""
    token = github_app.installation_token(installation_id)
    url, params = f"{github_app.API}/repos/{repo}/pulls/{number}/reviews", {"per_page": 100}
    while url:
        r = github_app._call("GET", url, headers=github_app._headers(token), params=params)
        found = next((x for x in r.json() if marker(key) in (x.get("body") or "")), None)
        if found:
            return found
        url, params = r.links.get("next", {}).get("url"), None
    return None


def post_review(installation_id, repo, number, commit_id, body, comments) -> dict:
    """One review, event COMMENT, with inline comments on the right side. GitHub's answer."""
    token = github_app.installation_token(installation_id)
    payload = {"body": body, "event": "COMMENT"}
    if comments:
        payload["comments"] = [{"path": c["path"], "line": c["line"], "side": "RIGHT", "body": c["body"]} for c in comments]
    if commit_id:
        payload["commit_id"] = commit_id
    return github_app._json("POST", f"{github_app.API}/repos/{repo}/pulls/{number}/reviews",
                            headers=github_app._headers(token), json=payload)


# --- taking a request ----------------------------------------------------------------------------------

def user_for(github_id) -> User | None:
    """The live Otto account linked to this GitHub user id."""
    with get_db() as s:
        return s.exec(select(User).where(User.github_id == github_id, User.deleted_at.is_(None))).first()


def live_user(user_id) -> User | None:
    with get_db() as s:
        user = s.get(User, user_id)
    return user if user is not None and user.deleted_at is None else None


def model_for(user) -> str | None:
    """OTTO_REVIEW_MODEL while it's available; else the user's default model while it's
    available, else the server's (None if none is)."""
    if config.REVIEW_MODEL:
        if config.is_available(config.REVIEW_MODEL):
            return config.REVIEW_MODEL
        log(f"OTTO_REVIEW_MODEL {config.REVIEW_MODEL!r} isn't available: using the user's default")
    for model in (user.default_model, config.DEFAULT_MODEL):
        if model and config.is_available(model):
            return model
    return None


def _repo(user, name) -> dict | None:
    try:
        return github_app.repo_access(user.id, name)
    except github_app.GitHubError as e:
        log(f"can't list {user.id}'s repos: {e}")
        return None


def _who(job) -> tuple[User, str, str] | None:
    """(user, key, trigger) of a request worth taking, or None (logged: never answered)."""
    where = f"{job['repo']}#{job['number']}"
    if job["type"] == "mention":
        where = f"comment {job['comment_id']} on {where}"
        if job.get("association") not in review.ASSOCIATIONS:
            log(f"ignored {where}: @{job.get('author_login')} is {job.get('association')}, not an owner, member or collaborator")
            return None
        user = user_for(job["author_id"])
        if user is None:
            log(f"ignored {where}: @{job.get('author_login')} has no Otto account linked")
            return None
        return user, f"comment:{job['comment_id']}", "mention"
    setting = review.auto_review(job["repo"])
    if setting is None:
        log(f"ignored {where}: auto-review is off")
        return None
    user = live_user(setting.user_id)
    if user is None:
        log(f"ignored {where}: the account that turned auto-review on is gone")
        return None
    return user, f"auto:{job['repo'].lower()}#{job['number']}@{job['head_sha']}", "auto"


def take(job) -> str | None:
    """Take a review request (blocking): the new review chat's id, to queue for the brain, or None
    when there's nothing to review (see the module's docstring)."""
    found = _who(job)
    if found is None:
        return None
    user, key, trigger = found
    repo = _repo(user, job["repo"])
    if repo is None:
        log(f"ignored {key}: {job['repo']} isn't in user {user.id}'s installations")
        return None
    name, number, iid = repo["full_name"], job["number"], repo["installation_id"]
    if not review.claim(key, user.id, name, number, trigger, job.get("comment_id")):
        log(f"ignored {key}: taken already (a delivery again)")
        return None
    if trigger == "mention" and config.REVIEW_REACTION:
        react(iid, name, job["comment_id"])
    if usage.limit_status(user.id):
        log(f"{key}: user {user.id} is at the daily limit")
        if trigger == "mention":
            comment(iid, name, number, review.LIMIT_TEXT)
        review.move(key, "limited")
        return None
    try:
        pr = pull(iid, name, number)
        if trigger == "auto" and pr.get("draft"):
            log(f"ignored {key}: a draft")
            review.move(key, "ignored")
            return None
        files = pull_files(iid, name, number)
    except github_app.GitHubError as e:
        log(f"{key}: can't read the pull request: {e}")
        review.move(key, "failed")
        return None
    model = model_for(user)
    if model is None:
        log(f"{key}: no model is available")
        review.move(key, "failed")
        return None
    sid = new_chat(user, model, name, pr, files, job, trigger)
    review.move(key, "queued", session_id=sid)
    return sid


def new_chat(user, model, repo, pr, files, job, trigger) -> str:
    """The review's chat: kind "review", titled "Review: <PR title>", holding the request."""
    sid = uuid.uuid4().hex[:10]
    title = (pr.get("title") or f"#{job['number']}").strip()
    create_session(sid, task=f"Review {repo}#{job['number']}: {title}", repo=None, model=model, status="provisioning",
                   user_id=user.id, kind="review", title=TITLE.format(title=title))
    picked = review.select_files(files)
    head, base = pr.get("head") or {}, pr.get("base") or {}
    append_event(sid, review.EVENT_REQUESTED, {
        "repo": repo, "number": job["number"], "title": title, "body": (pr.get("body") or "")[:review.SUMMARY_MAX],
        "url": pr.get("html_url") or f"{github_app.WEB}/{repo}/pull/{job['number']}",
        "author": (pr.get("user") or {}).get("login"), "head": head.get("ref"), "base": base.get("ref"),
        "head_sha": head.get("sha") or job.get("head_sha"), "trigger": trigger,
        "requested_by": job.get("author_login") if trigger == "mention" else None,
        "comment": job.get("comment") if trigger == "mention" else None,
        "additions": pr.get("additions"), "deletions": pr.get("deletions"),
        "total_files": pr.get("changed_files") or len(files), **picked})
    return sid


async def enqueue(ch, sid):
    """Queue the review chat's first turn for a brain worker."""
    transition(sid, "queued", {"provisioning"})
    try:
        await ch.default_exchange.publish(Message(json.dumps(review_job(sid)).encode(),
                                                  delivery_mode=DeliveryMode.PERSISTENT), routing_key=SESSIONS_QUEUE)
    except Exception as e:
        append_event(sid, "error", {"stage": "enqueue", "message": f"{type(e).__name__}: {e}"[:2000]})
        transition(sid, "failed", {"queued"})


# --- posting ---------------------------------------------------------------------------------------------

POSTABLE = ("claimed", "queued", "limited", "failed")  # never "posting" or "posted": one review per request


def _inline_text(comments) -> str:
    return "\n\n".join(f"**{c['path']}:{c['line']}**\n{c['body']}" for c in comments)


def post(sid) -> dict | None:
    """Post the chat's review on GitHub, once: review.posted {review_id, url, comments}, or
    review.failed. None if there's nothing to post or it's posted (or posting) already."""
    row, draft = review.for_session(sid), review.latest(sid, review.EVENT_DRAFTED)
    req = review.latest(sid, review.EVENT_REQUESTED)
    if row is None or draft is None or req is None:
        log(f"{sid}: nothing to post")
        return None
    if not review.move(row.key, "posting", POSTABLE):
        log(f"{row.key}: posted already")
        return None
    user = live_user(row.user_id)
    repo = _repo(user, row.repo) if user else None
    if repo is None:
        return _failed(row, sid, f"{row.repo} isn't reachable through the user's installations any more")
    args = (repo["installation_id"], repo["full_name"], row.number, req.get("head_sha"))
    comments, tag = draft["comments"], f"\n\n{marker(row.key)}"
    try:
        if out := posted_review(*args[:3], row.key):  # it went through before: record it, post nothing
            log(f"{row.key}: on GitHub already (review {out.get('id')})")
            return _posted(row, sid, out, None, draft)
        try:
            out = post_review(*args, draft["summary"] + tag, comments)
        except github_app.GitHubError as e:
            if not comments or "-> 422" not in str(e):
                raise
            # the pull request moved on since the diff was read: the comments go in the body
            log(f"{row.key}: GitHub refused the inline comments ({e}); posting them in the summary")
            out = post_review(*args, f"{draft['summary']}\n\n{_inline_text(comments)}{tag}", [])
            comments = []
    except github_app.GitHubError as e:
        return _failed(row, sid, str(e))
    return _posted(row, sid, out, len(comments), draft)


def _posted(row, sid, out, comments, draft):
    posted = {"review_id": out.get("id"), "url": out.get("html_url"),
              "comments": len(draft["comments"]) if comments is None else comments}
    append_event(sid, review.EVENT_POSTED, posted)
    review.move(row.key, "posted", review_id=out.get("id"))
    log(f"{row.key}: posted ({posted['comments']} inline, {draft.get('dropped', 0)} dropped)")
    return posted


def _failed(row, sid, why):
    log(f"{row.key}: couldn't post: {why}")
    append_event(sid, review.EVENT_FAILED, {"message": "GitHub didn't take the review. Retry, or ask again on GitHub."})
    review.move(row.key, "failed")
    return None


def rebuild(sid) -> bool:
    """Retry in a failed review chat whose review is written: no model call and nothing new on
    GitHub. The chat is rebuilt from what's stored (the review's text, for follow-ups, if the turn
    failed before storing it) and ends done. True if it was posted already; False: the caller
    queues it for posting (post() never posts twice)."""
    draft = review.latest(sid, review.EVENT_DRAFTED)
    stored = any(e.type == "llm.message" and e.payload.get("review") is True for e in load_events(sid))
    if not stored:
        append_event(sid, "llm.message", {"message": {"role": "assistant", "content": review.as_text(draft)},
                                          "review": True})
    transition(sid, "done", {"failed", "interrupted"})
    row = review.for_session(sid)
    return review.latest(sid, review.EVENT_POSTED) is not None or (row is not None and row.state in ("posting", "posted"))


def limited(sid):
    """The daily limit stopped the review in the brain: say so once on the pull request (mentions only)."""
    row = review.for_session(sid)
    if row is None or not review.move(row.key, "limited", ("queued",)):
        return
    user = live_user(row.user_id)
    repo = _repo(user, row.repo) if user else None
    if repo and row.trigger == "mention":
        comment(repo["installation_id"], repo["full_name"], row.number, review.LIMIT_TEXT)


# --- the otto.reviews consumer --------------------------------------------------------------------------

async def handle(job, ch):
    kind, sid = job.get("type"), job.get("session_id")
    if kind in ("mention", "auto"):
        if sid := await asyncio.to_thread(take, job):
            await enqueue(ch, sid)
    elif kind == "drafted" and isinstance(sid, str):
        await asyncio.to_thread(post, sid)
    elif kind == "limited" and isinstance(sid, str):
        await asyncio.to_thread(limited, sid)
    elif kind == "failed":
        log(f"{sid}: the brain couldn't write the review (the chat says why; Retry there)")


async def consume(queue, ch):
    """Apply otto.reviews' messages until cancelled. One that fails is logged and dropped."""
    async with queue.iterator() as it:
        async for msg in it:
            async with msg.process():
                try:
                    job = json.loads(msg.body)
                    await handle(job if isinstance(job, dict) else {}, ch)
                except Exception as e:
                    log(f"dropped an otto.reviews message: {type(e).__name__}: {e}")


# --- Settings → GitHub: auto-review -------------------------------------------------------------------

def setting_json(setting, user) -> dict | None:
    """A repo's auto-review, as GET /repos shows it: who turned it on, or None while it's off."""
    if setting is None:
        return None
    if setting.user_id == user.id:
        return {"by": user.github_login or user.name, "mine": True}
    other = live_user(setting.user_id)
    return {"by": (other.github_login or other.name) if other else None, "mine": False}


class AutoReviewBody(BaseModel):
    enabled: bool


@router.put("/repos/{owner}/{name}/auto-review")
async def put_auto_review(owner: str, name: str, body: AutoReviewBody, user: User = Depends(auth.verified_user)):
    """Review new pull requests automatically (on the user's daily limit), or not. 404 unless one
    of the user's installations can reach the repo."""
    found = await asyncio.to_thread(github_app.repo_access, user.id, f"{owner}/{name}")
    if found is None:
        raise HTTPException(404, f"{owner}/{name} isn't one of your repos")
    setting = await asyncio.to_thread(review.set_auto_review, found["full_name"], user.id, body.enabled)
    return {"full_name": found["full_name"], "auto_review": setting_json(setting, user)}
