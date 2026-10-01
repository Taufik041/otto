"""Access tokens, refresh tokens and WebSocket tickets.

An access token is a short-lived JWT (HS256, AUTH_SECRET, ACCESS_TOKEN_MINUTES) the client sends as
`Authorization: Bearer <token>`. It carries the user's token_version: bumping that (logout-all, a
password change or reset) voids every access token at once.

A refresh token is an opaque random string, kept by the browser in an httpOnly cookie that only
reaches /auth, and stored here only as its sha256. Each sign-in starts a family; /auth/refresh
swaps the token for the next one in its family. A token that was already swapped out coming back
means someone kept a copy: the whole family is revoked, so both the thief and the user have to
sign in again.

A WebSocket ticket is a random, single-use string good for TICKET_TTL seconds on one session's
WebSocket, so access tokens never go into URLs (and server logs). Tickets live in this process's
memory: fine for one gateway.
"""
import hashlib, secrets, time, uuid
from datetime import timedelta

import jwt
from sqlmodel import select, update

from shared import config
from shared.db import get_db
from shared.models import RefreshToken, User, as_utc, utcnow

MIN_SECRET = 32
TICKET_TTL = 30  # seconds
USER_AGENT_MAX = 300

_tickets: dict[str, tuple[float, str, str]] = {}  # ticket -> (valid until, user id, session id)


def check_secret():
    if not config.AUTH_SECRET or len(config.AUTH_SECRET) < MIN_SECRET:
        raise RuntimeError(f"set AUTH_SECRET to a random string of at least {MIN_SECRET} characters, "
                           "e.g. python -c 'import secrets; print(secrets.token_urlsafe(48))'")


def sha256(text) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def now() -> float:
    return time.monotonic()


# --- access tokens --------------------------------------------------------------------

def access_ttl() -> timedelta:
    return timedelta(minutes=config.ACCESS_TOKEN_MINUTES)


def access_token(user: User) -> str:
    check_secret()
    issued = utcnow()
    claims = {"sub": user.id, "ver": user.token_version, "type": "access", "jti": uuid.uuid4().hex,
              "iat": issued, "exp": issued + access_ttl()}
    return jwt.encode(claims, config.AUTH_SECRET, algorithm="HS256")


def access_claims(token) -> dict | None:
    """The claims of a valid, unexpired access token, else None. The caller checks ver."""
    check_secret()
    try:
        claims = jwt.decode(token or "", config.AUTH_SECRET, algorithms=["HS256"],
                            options={"require": ["sub", "exp", "iat"]})
    except jwt.InvalidTokenError:  # including any token with an audience: those are for other things
        return None
    return claims if claims.get("type") == "access" else None


# --- refresh tokens -------------------------------------------------------------------

def refresh_ttl() -> timedelta:
    return timedelta(days=config.REFRESH_TOKEN_DAYS)


def _new_refresh(user_id, family_id, user_agent) -> tuple[str, RefreshToken]:
    token = secrets.token_urlsafe(48)
    row = RefreshToken(id=uuid.uuid4().hex, user_id=user_id, family_id=family_id, token_hash=sha256(token),
                       expires_at=utcnow() + refresh_ttl(), user_agent=user_agent[:USER_AGENT_MAX] if user_agent else None)
    return token, row


def issue_refresh(user_id, user_agent=None) -> str:
    """A refresh token in a new family: a new sign-in."""
    token, row = _new_refresh(user_id, uuid.uuid4().hex, user_agent)
    with get_db() as s:
        s.add(row)
    return token


def _find(s, token) -> RefreshToken | None:
    return s.exec(select(RefreshToken).where(RefreshToken.token_hash == sha256(token))).first() if token else None


def _revoke(s, *where):
    s.exec(update(RefreshToken).where(*where, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))


def rotate_refresh(token, user_agent=None) -> tuple[str, str] | None:
    """(user id, the family's next token) for a live refresh token, revoking it. None for an
    unknown or expired token; for one already revoked, None after revoking its whole family."""
    with get_db() as s:
        row = _find(s, token)
        if row is None or as_utc(row.expires_at) <= utcnow():
            return None
        new_token, new = _new_refresh(row.user_id, row.family_id, user_agent)
        # claimed atomically: of two requests with the same token, the second one is a reuse
        claimed = s.exec(update(RefreshToken).where(RefreshToken.id == row.id, RefreshToken.revoked_at.is_(None))
                         .values(revoked_at=utcnow(), replaced_by_id=new.id)).rowcount
        if not claimed:
            print(f"[auth] refresh token reused: revoked family {row.family_id} of user {row.user_id}", flush=True)
            _revoke(s, RefreshToken.family_id == row.family_id)
            return None
        s.add(new)
    return row.user_id, new_token


def refresh_user(token) -> str | None:
    """The user id of a live refresh token, without rotating it."""
    with get_db() as s:
        row = _find(s, token)
    if row is None or row.revoked_at is not None or as_utc(row.expires_at) <= utcnow():
        return None
    return row.user_id


def revoke_family(token):
    """Revoke the token's family: signs out the device it was issued to."""
    with get_db() as s:
        if row := _find(s, token):
            _revoke(s, RefreshToken.family_id == row.family_id)


def revoke_all(user_id, s=None):
    """Revoke every refresh token of the user; in the caller's transaction s, if given."""
    if s is not None:
        return _revoke(s, RefreshToken.user_id == user_id)
    with get_db() as s:
        _revoke(s, RefreshToken.user_id == user_id)


# --- WebSocket tickets ----------------------------------------------------------------

def issue_ticket(user_id, sid) -> str:
    t = now()
    for k in [k for k, (until, _, _) in _tickets.items() if until <= t]:
        del _tickets[k]
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (t + TICKET_TTL, user_id, sid)
    return ticket


def take_ticket(ticket, sid) -> str | None:
    """The user id of a live ticket for session sid, using it up; None otherwise."""
    hit = _tickets.pop(ticket, None) if ticket else None
    if hit is None or hit[0] <= now() or hit[2] != sid:
        return None
    return hit[1]
