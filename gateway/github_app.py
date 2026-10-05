"""GitHub: the App's credentials, its user OAuth (sign-in, linking, installing), and each user's repos.

Every call to GitHub goes through request(), which the tests replace.

There is no separate setup URL: with "Request user authorization (OAuth) during installation" on,
GitHub sends installs and updates to the callback URL too, so /auth/github/callback handles both
flows. An installation_id from the query is never trusted on its own: it must show up in
GET /user/installations for the user who just authorized. Repos picked on github.com come back
as setup_action=update without Otto's state: that only refreshes caches, for a signed-in user
whose GitHub confirms the installation, and never links anything.

The frontend starts a flow with POST /auth/github/url (sign in, or link GitHub to the signed-in
account) or POST /github/install-url, and sends the browser to the URL it gets back. The OAuth
state is a signed token (auth.sign, audience "github-state") holding the flow, the user who
started it (for a link or an install), and a nonce that must match a cookie set in this browser.
So a state (and code) started by someone else can't be replayed in a victim's browser to link the
attacker's GitHub account to the victim's Otto account. Each state has its own cookie
(nonce_cookie), so a second start (a prefetch, a double click, a reload) doesn't void the first.

The callback is a top-level GET from github.com, so it carries no access token; the refresh
cookie does reach it (SameSite=Lax, Path=/auth). A sign-in ends with a new refresh cookie and a
redirect to FRONTEND_URL/auth/callback, where the frontend calls /auth/refresh.
"""
import hashlib, json, jwt, secrets, time, uuid
from datetime import timedelta
from urllib.parse import quote, urlencode

import requests
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from gateway import auth, tokens
from shared import config
from shared.db import get_db
from shared.models import Installation, User

API = "https://api.github.com"
WEB = "https://github.com"
TIMEOUT = 15  # seconds per GitHub request
STATE_TTL = timedelta(minutes=10)
BAD_CLIENT = "GitHub rejected Otto's client credentials — check GITHUB_CLIENT_ID/SECRET"
NONCE_PATH = "/auth/github"  # sent to the callback only
TOKEN_REUSE = 50 * 60  # seconds to reuse an installation token (they last an hour)
REPOS_TTL = 60         # seconds to reuse a user's repo list

_tokens: dict[int, tuple[float, str]] = {}         # installation id -> (reuse until, token)
_repos: dict[str, tuple[float, list[dict]]] = {}   # user id -> (fresh until, repos)

router = APIRouter()


class GitHubError(Exception):
    """GitHub answered with an error, or not at all."""


class BadClientCredentials(GitHubError):
    """GitHub refused GITHUB_CLIENT_ID/GITHUB_CLIENT_SECRET: a server misconfiguration."""


def request(method, url, **kw) -> requests.Response:
    return requests.request(method, url, timeout=TIMEOUT, **kw)


def _call(method, url, **kw):
    try:
        r = request(method, url, **kw)
    except requests.RequestException as e:
        raise GitHubError(f"{method} {url}: {type(e).__name__}: {e}") from None
    if r.status_code >= 400:
        raise GitHubError(f"{method} {url} -> {r.status_code}: {r.text[:300]}")
    return r


def _json(method, url, **kw):
    return _call(method, url, **kw).json()


def _pages(url, token, key) -> list:
    """Every item of a paginated list whose items are under `key`, following Link: rel=next."""
    items, params = [], {"per_page": 100}
    while url:
        r = _call("GET", url, headers=_headers(token), params=params)
        items += r.json()[key]
        url, params = r.links.get("next", {}).get("url"), None  # the next link carries the query
    return items


def now() -> float:
    return time.monotonic()


def _headers(token) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


# --- the App itself -------------------------------------------------------------------

def make_jwt():
    if not (config.GITHUB_APP_ID and config.GITHUB_APP_KEY_PATH):
        raise GitHubError("the GitHub App isn't configured: set GITHUB_APP_ID and GITHUB_APP_KEY_PATH")
    try:
        key = open(config.GITHUB_APP_KEY_PATH).read()
    except OSError as e:
        raise GitHubError(f"can't read GITHUB_APP_KEY_PATH: {e}") from None
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": config.GITHUB_APP_ID}
    return jwt.encode(payload, key, algorithm="RS256")


def mint_token(installation_id, repositories=None) -> str:
    """A new installation token (1h); repositories (repo names) narrows it to just those."""
    return _json("POST", f"{API}/app/installations/{installation_id}/access_tokens", headers=_headers(make_jwt()),
                 json={"repositories": repositories} if repositories else None)["token"]


def installation_token(installation_id) -> str:
    """An installation token for reading, reused for TOKEN_REUSE seconds."""
    hit = _tokens.get(installation_id)
    if hit and now() < hit[0]:
        return hit[1]
    token = mint_token(installation_id)
    _tokens[installation_id] = (now() + TOKEN_REUSE, token)
    return token


def forget(user_id=None, installation_id=None):
    """Drop a user's cached repo list and an installation's cached token."""
    _repos.pop(user_id, None)
    _tokens.pop(installation_id, None)


def forget_all():
    _tokens.clear()
    _repos.clear()


# --- a user's installations and repos -----------------------------------------------------

def installations_of(user_id) -> list[Installation]:
    with get_db() as s:
        return list(s.exec(select(Installation).where(Installation.user_id == user_id)
                           .order_by(Installation.created_at)).all())


def user_repos(user_id) -> list[dict]:
    """The repos of all the user's installations, newest first (cached for REPOS_TTL seconds)."""
    hit = _repos.get(user_id)
    if hit and now() < hit[0]:
        return hit[1]
    repos = []
    for inst in installations_of(user_id):
        try:
            found = _pages(f"{API}/installation/repositories", installation_token(inst.id), "repositories")
        except GitHubError as e:  # e.g. uninstalled on GitHub: list the others
            print(f"[github] skipped installation {inst.id} of user {user_id}: {e}", flush=True)
            continue
        repos += [{"full_name": r["full_name"], "private": r["private"], "updated_at": r["updated_at"],
                   "default_branch": r["default_branch"], "installation_id": inst.id} for r in found]
    repos.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    _repos[user_id] = (now() + REPOS_TTL, repos)
    return repos


def repo_access(user_id, full_name) -> dict | None:
    """The user's repo called full_name ("owner/name", any case), with its installation, or None."""
    want = full_name.strip().lower()
    return next((r for r in user_repos(user_id) if r["full_name"].lower() == want), None)


# --- user OAuth -------------------------------------------------------------------------

def _need_oauth():
    if not (config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET):
        raise HTTPException(503, "GitHub sign-in is not configured: set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET")


def nonce_cookie(nonce) -> str:
    """The name of the cookie that remembers one state's nonce in the browser that started it."""
    return "gh_nonce_" + hashlib.sha256(nonce.encode()).hexdigest()[:12]


def _with_state(response: Response, url, params, flow, user: User | None) -> str:
    """url with a new state for `flow` started by user (None: signed out); the state's nonce is
    remembered in this browser by a cookie on response."""
    nonce = secrets.token_urlsafe(24)
    state = auth.sign({"flow": flow, "uid": user.id if user else None, "nonce": nonce}, "github-state", STATE_TTL)
    response.set_cookie(nonce_cookie(nonce), nonce, max_age=int(STATE_TTL.total_seconds()), httponly=True,
                        samesite="lax", secure=config.COOKIE_SECURE, path=NONCE_PATH)
    return f"{url}?{urlencode({**params, 'state': state})}"


def _check_state(request: Request, state) -> dict:
    """The state's claims if it is valid and was started in this browser."""
    claims = auth.verify(state, "github-state") if state else None
    nonce = str((claims or {}).get("nonce", ""))
    cookie = request.cookies.get(nonce_cookie(nonce)) if nonce else None
    if not cookie or not secrets.compare_digest(nonce, cookie):
        raise HTTPException(400, "invalid or expired GitHub state; start again")
    return claims


def _browser_user(request: Request) -> User | None:
    """Whoever is signed in in this browser, by its refresh cookie (not rotated)."""
    user_id = tokens.refresh_user(request.cookies.get(auth.REFRESH_COOKIE))
    if user_id is None:
        return None
    with get_db() as s:
        return s.get(User, user_id)


def _flow_user(claims, browser: User | None) -> User | None:
    """Who the flow is for: the user who started it, else whoever is signed in in this browser.
    A state started signed out is fine for a signed-in user (a prefetch may come without
    cookies): GitHub is then linked to them, and never made a second account."""
    uid = claims.get("uid")
    if uid is None:
        return browser
    if browser is not None and browser.id != uid:
        raise HTTPException(400, "you signed in or out since this started; start again")
    with get_db() as s:
        user = s.get(User, uid)
    if user is None:
        raise HTTPException(400, "that account no longer exists; start again")
    return user


def _finish(url, claims) -> RedirectResponse:
    """Redirect to the frontend, dropping the state's nonce cookie: a state works once."""
    r = RedirectResponse(url, 302)
    r.delete_cookie(nonce_cookie(claims["nonce"]), httponly=True, samesite="lax", secure=config.COOKIE_SECURE,
                    path=NONCE_PATH)
    return r


def _no_secret(text) -> str:
    secret = config.GITHUB_CLIENT_SECRET
    return text.replace(secret, "[REDACTED]") if secret else text


def exchange_code(code) -> str:
    """A user access token for an OAuth code. A refusal carries GitHub's answer, minus the secret."""
    try:
        body = _json("POST", f"{WEB}/login/oauth/access_token", headers={"Accept": "application/json"},
                     data={"client_id": config.GITHUB_CLIENT_ID, "client_secret": config.GITHUB_CLIENT_SECRET,
                           "code": code})
    except GitHubError as e:
        raise GitHubError(_no_secret(str(e))) from None
    if not body.get("access_token"):
        shown = json.dumps({k: v for k, v in body.items() if k != "access_token"})
        error = BadClientCredentials if body.get("error") == "incorrect_client_credentials" else GitHubError
        raise error(_no_secret(f"code exchange failed: {shown}"))
    return body["access_token"]


def _refused(e: GitHubError, message) -> HTTPException:
    """The 400 for a failed exchange: a misconfigured server says so; anything else, `message`."""
    return HTTPException(400, BAD_CLIENT if isinstance(e, BadClientCredentials) else message)


def github_user(user_token) -> dict:
    return _json("GET", f"{API}/user", headers=_headers(user_token))


def _authorize(response: Response, user: User | None) -> str:
    return _with_state(response, f"{WEB}/login/oauth/authorize", {"client_id": config.GITHUB_CLIENT_ID},
                       "signin", user)


class GitHubUrl(BaseModel):
    mode: Literal["signin", "link"] = "signin"


@router.post("/auth/github/url")
def github_url(body: GitHubUrl, response: Response, user: User | None = Depends(auth.optional_user)):
    """Where to send the browser to sign in with GitHub, or (mode "link", signed in) to link
    GitHub to this account. Sets the state's nonce cookie, so call it from the browser."""
    _need_oauth()
    if body.mode == "link" and user is None:
        raise HTTPException(401, "sign in first", headers={"WWW-Authenticate": "Bearer"})
    return {"url": _authorize(response, user if body.mode == "link" else None)}


@router.get("/auth/github/start")
def github_start():
    """Sign in with GitHub straight from the browser's address bar (handy for manual tests). It
    links GitHub to whoever is signed in in this browser, if anyone."""
    _need_oauth()
    r = RedirectResponse("", 302)
    r.headers["location"] = _authorize(r, None)  # the cookie and the URL come together
    return r


@router.post("/github/install-url")
def github_install_url(response: Response, user: User = Depends(auth.current_user)):
    """Where to send the browser to install the App (or change its repos) on GitHub, which comes
    back to the callback. Sets the state's nonce cookie, so call it from the browser."""
    _need_oauth()
    if not config.GITHUB_APP_SLUG:
        raise HTTPException(503, "set GITHUB_APP_SLUG to the App's name in its github.com/apps/<slug> URL")
    return {"url": _with_state(response, f"{WEB}/apps/{config.GITHUB_APP_SLUG}/installations/new", {},
                               "install", user)}


@router.get("/auth/github/callback")
def github_callback(request: Request, state: str | None = None, code: str | None = None,
                    error: str | None = None, installation_id: int | None = None,
                    setup_action: str | None = None):
    """Both flows come back here: an install or update (installation_id and setup_action in the
    query), or a sign-in / account link."""
    if state is None and setup_action == "update" and installation_id is not None:
        return _updated_on_github(_browser_user(request), installation_id, code)
    claims = _check_state(request, state)
    user = _flow_user(claims, _browser_user(request))
    if error:  # the user cancelled on GitHub
        return _finish(f"{config.FRONTEND_URL}/?github_error={quote(error)}", claims)
    installing = installation_id is not None and setup_action is not None
    if installing != (claims["flow"] == "install"):
        raise HTTPException(400, "unexpected GitHub callback; start again")
    if installing:
        if user is None:
            raise HTTPException(400, "unexpected GitHub callback; start again")
        return _installed(user, installation_id, setup_action, code, claims)
    if not code:
        raise HTTPException(400, "unexpected GitHub callback; start again")
    try:
        gh = github_user(exchange_code(code))
    except GitHubError as e:
        print(f"[github] sign-in failed: {e}", flush=True)
        raise _refused(e, "GitHub sign-in failed; try again") from None
    user = _sign_in(user, gh)
    r = _finish(f"{config.FRONTEND_URL}/auth/callback", claims)
    auth.set_refresh(r, tokens.issue_refresh(user.id, request.headers.get("user-agent")))
    return r


def _sign_in(current: User | None, gh: dict) -> User:
    """The user for this GitHub account: the signed-in one (linking it), the one already linked
    to it, or a new one. Never matched by email: that would hand over accounts."""
    with get_db() as s:
        linked = s.exec(select(User).where(User.github_id == gh["id"])).first()
        if current is not None:
            if linked is not None and linked.id != current.id:
                raise HTTPException(409, "this GitHub account is linked to another Otto account")
            user = s.get(User, current.id)
            if user.github_id not in (None, gh["id"]):
                raise HTTPException(409, "your account is linked to a different GitHub account")
        else:
            user = linked or User(id=uuid.uuid4().hex, name=gh.get("name") or gh["login"])
        user.github_id, user.github_login, user.avatar_url = gh["id"], gh["login"], gh.get("avatar_url")
        s.add(user)
        try:
            s.flush()
        except IntegrityError:  # a concurrent sign-in linked it first
            raise HTTPException(409, "this GitHub account is linked to another Otto account") from None
    return user


def _confirmed(code) -> tuple[str, dict[int, dict]]:
    """Exchange the code; the user token and the installations that GitHub user can access."""
    if not code:
        raise HTTPException(400, "GitHub sent no authorization code; start again")
    try:
        token = exchange_code(code)
        return token, {i["id"]: i for i in _pages(f"{API}/user/installations", token, "installations")}
    except GitHubError as e:
        print(f"[github] install check failed: {e}", flush=True)
        raise _refused(e, "GitHub didn't confirm the installation; try again") from None


def _updated_on_github(user: User | None, installation_id: int, code: str | None):
    """Repos picked on github.com (no state of ours): refresh the caches, if the user is signed in
    and GitHub says the one who authorized can access the installation. Links nothing."""
    if user is None:
        raise HTTPException(400, "sign in to Otto, then change the repos from Settings")
    _, mine = _confirmed(code)
    if installation_id not in mine:
        raise HTTPException(400, "that installation isn't one your GitHub account can access")
    forget(user.id, installation_id)
    return RedirectResponse(f"{config.FRONTEND_URL}/settings/github", 302)


def _installed(user: User, installation_id: int, setup_action: str, code: str | None, claims):
    done = _finish(f"{config.FRONTEND_URL}/settings/github", claims)
    with get_db() as s:
        linked = s.get(Installation, installation_id)
    if setup_action == "update" and linked is not None and linked.user_id == user.id:
        forget(user.id, installation_id)  # the user changed which repos the App sees
        return done
    token, mine = _confirmed(code)
    try:
        gh = github_user(token)
    except GitHubError as e:
        print(f"[github] install check failed: {e}", flush=True)
        raise _refused(e, "GitHub didn't confirm the installation; try again") from None
    if installation_id not in mine:
        raise HTTPException(403, "that installation isn't one your GitHub account can access")
    with get_db() as s:
        row = s.get(Installation, installation_id)
        if row is not None and row.user_id != user.id:
            raise HTTPException(409, "this installation is connected to another Otto account")
        row = row or Installation(id=installation_id, user_id=user.id, account_login="")
        row.account_login = mine[installation_id]["account"]["login"]
        s.add(row)
        # the GitHub account that authorized is this user's, unless it is linked to someone else
        u = s.get(User, user.id)
        taken = s.exec(select(User).where(User.github_id == gh["id"], User.id != user.id)).first()
        if u.github_id == gh["id"] or (u.github_id is None and taken is None):
            u.github_id, u.github_login, u.avatar_url = gh["id"], gh["login"], gh.get("avatar_url")
            s.add(u)
    forget(user.id, installation_id)
    return done


# --- pull requests ------------------------------------------------------------------

def _pull_error(r) -> str:
    """"Validation Failed; A pull request already exists for o:otto/x." from GitHub's answer."""
    try:
        data = r.json()
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    parts = [data.get("message") or f"HTTP {r.status_code}"]
    parts += [e.get("message") or e.get("code") for e in data.get("errors") or [] if isinstance(e, dict)]
    return "; ".join(p for p in parts if p)


def open_pull(installation_id, full_name, title, body, head, base) -> dict:
    """Open the pull request head -> base on full_name with the installation's token; if one is
    already open for head, that one. Its {number, html_url, title, ...}. GitHubError with a plain
    message (never the token) when GitHub refuses or can't be reached."""
    token = installation_token(installation_id)
    url = f"{API}/repos/{full_name}/pulls"
    try:
        r = request("POST", url, headers=_headers(token), json={"title": title, "body": body, "head": head, "base": base})
        if r.status_code < 400:
            return r.json()
        msg = _pull_error(r)
        if r.status_code == 422 and "already exists" in msg:
            owner = full_name.split("/")[0]
            found = request("GET", url, headers=_headers(token), params={"head": f"{owner}:{head}", "state": "open"})
            if found.status_code < 400 and found.json():
                return found.json()[0]
    except requests.RequestException as e:
        msg = f"GitHub couldn't be reached ({type(e).__name__})"
    raise GitHubError(msg.replace(token, "[REDACTED]"))


@router.get("/github")
def github_status(user: User = Depends(auth.current_user)):
    rows = installations_of(user.id)
    return {"connected": bool(rows), "login": user.github_login, "avatar_url": user.avatar_url,
            "installations": [{"id": r.id, "account_login": r.account_login} for r in rows]}


@router.delete("/github/installations/{installation_id}")
def unlink_installation(installation_id: int, user: User = Depends(auth.current_user)):
    """Disconnect an installation from Otto. The App stays installed on GitHub until the user
    uninstalls it at uninstall_url."""
    with get_db() as s:
        row = s.get(Installation, installation_id)
        if row is None or row.user_id != user.id:
            raise HTTPException(404, f"no installation {installation_id}")
        s.delete(row)
    forget(user.id, installation_id)
    own = (row.account_login or "").lower() == (user.github_login or "").lower()
    where = "settings" if own else f"organizations/{row.account_login}/settings"
    return {"id": installation_id, "uninstall_url": f"{WEB}/{where}/installations/{installation_id}"}


@router.get("/repos")
def repos(user: User = Depends(auth.current_user)):
    """The user's repos across their installations, for the @ mention: newest first."""
    return user_repos(user.id)
