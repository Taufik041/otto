"""GitHub: the App's own credentials, and its user OAuth for sign-in and account linking.

Every call to GitHub goes through request(), which the tests replace.

The OAuth state is a signed token (auth.sign, audience "github-state") holding the flow, the user
signed in when it started, and a nonce that must match the NONCE_COOKIE set in this browser. So
a state (and code) started by someone else can't be replayed in a victim's browser to link the
attacker's GitHub account to the victim's Otto account.
"""
import jwt, secrets, time, uuid
from datetime import timedelta
from urllib.parse import quote, urlencode

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from gateway import auth
from shared import config
from shared.db import get_db
from shared.models import User

API = "https://api.github.com"
WEB = "https://github.com"
TIMEOUT = 15  # seconds per GitHub request
STATE_TTL = timedelta(minutes=10)
NONCE_COOKIE = "otto_oauth"
NONCE_PATH = "/auth/github"  # sent to the callback only

router = APIRouter()


class GitHubError(Exception):
    """GitHub answered with an error, or not at all."""


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


def _headers(token) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


# --- the App itself -------------------------------------------------------------------

def make_jwt():
    key = open(config.GITHUB_APP_KEY_PATH).read()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": config.GITHUB_APP_ID}
    return jwt.encode(payload, key, algorithm="RS256")


def get_installation_token():
    inst = config.GITHUB_INSTALLATION_ID
    return _json("POST", f"{API}/app/installations/{inst}/access_tokens", headers=_headers(make_jwt()))["token"]


def forget_all():
    """Drop every cache (tests; nothing is cached yet)."""


# --- user OAuth -------------------------------------------------------------------------

def _need_oauth():
    if not (config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET):
        raise HTTPException(503, "GitHub sign-in is not configured: set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET")


def _redirect_with_state(url, params, flow, user) -> RedirectResponse:
    """Redirect to GitHub with a new state for `flow`, and remember its nonce in this browser."""
    nonce = secrets.token_urlsafe(24)
    state = auth.sign({"flow": flow, "uid": user.id if user else None, "nonce": nonce}, "github-state", STATE_TTL)
    r = RedirectResponse(f"{url}?{urlencode({**params, 'state': state})}", 302)
    r.set_cookie(NONCE_COOKIE, nonce, max_age=int(STATE_TTL.total_seconds()), httponly=True, samesite="lax",
                 secure=config.COOKIE_SECURE, path=NONCE_PATH)
    return r


def _check_state(request: Request, state) -> dict:
    """The state's claims if it is valid, was started in this browser, by whoever is signed in now."""
    claims = auth.verify(state, "github-state") if state else None
    nonce = request.cookies.get(NONCE_COOKIE)
    if not claims or not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise HTTPException(400, "invalid or expired GitHub state; start again")
    user = auth.optional_user(request)
    if claims.get("uid") != (user.id if user else None):
        raise HTTPException(400, "you signed in or out since this started; start again")
    return claims


def _finish(url) -> RedirectResponse:
    r = RedirectResponse(url, 302)
    r.delete_cookie(NONCE_COOKIE, httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path=NONCE_PATH)
    return r


def exchange_code(code) -> str:
    """A user access token for an OAuth code."""
    body = _json("POST", f"{WEB}/login/oauth/access_token", headers={"Accept": "application/json"},
                 data={"client_id": config.GITHUB_CLIENT_ID, "client_secret": config.GITHUB_CLIENT_SECRET,
                       "code": code})
    if not body.get("access_token"):
        raise GitHubError(f"code exchange failed: {body.get('error') or 'no token'}")
    return body["access_token"]


def github_user(user_token) -> dict:
    return _json("GET", f"{API}/user", headers=_headers(user_token))


@router.get("/auth/github/start")
def github_start(request: Request):
    """Sign in with GitHub; when signed in already, link GitHub to this account."""
    _need_oauth()
    return _redirect_with_state(f"{WEB}/login/oauth/authorize", {"client_id": config.GITHUB_CLIENT_ID},
                                "signin", auth.optional_user(request))


@router.get("/auth/github/callback")
def github_callback(request: Request, state: str | None = None, code: str | None = None,
                    error: str | None = None):
    claims = _check_state(request, state)
    if error:  # the user cancelled on GitHub
        return _finish(f"{config.FRONTEND_URL}/?github_error={quote(error)}")
    if claims["flow"] != "signin" or not code:
        raise HTTPException(400, "unexpected GitHub callback; start again")
    try:
        gh = github_user(exchange_code(code))
    except GitHubError as e:
        print(f"[github] sign-in failed: {e}", flush=True)
        raise HTTPException(400, "GitHub sign-in failed; try again") from None
    user = _sign_in(auth.optional_user(request), gh)
    r = _finish(config.FRONTEND_URL)
    auth.set_login(r, user.id)
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
