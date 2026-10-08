"""Who may make a new account, and access requests.

OTTO_SIGNUP_MODE decides who may sign up: "open" (anyone), "allowlist" (GitHub logins in
OTTO_ALLOWED_GITHUB, emails in OTTO_ALLOWED_EMAILS, and approved access requests) or "closed"
(no one). OTTO_ACCEPTING=false pauses every signup whatever the mode. Existing users always keep
access: only making a new account is checked. An email signup is checked by its email, a GitHub
signup by its login (GitHub's email is never used to match anything).
"""
import re

from sqlalchemy.exc import IntegrityError
from sqlmodel import or_, select

from shared import config
from shared.db import get_db
from shared.models import AccessRequest, utcnow

GITHUB_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
MAX_NOTE = 500

INVITE_ONLY = "Otto is invite-only right now."
PAUSED = "Otto isn't taking new accounts right now."


def normal_login(v) -> str:
    """A GitHub login, lower-cased, without a leading @; ValueError for anything else."""
    v = v.strip().removeprefix("@")
    if not GITHUB_LOGIN.fullmatch(v):
        raise ValueError("not a GitHub username")
    return v.lower()


def _approved(s, github_login=None, email=None) -> bool:
    keys = [AccessRequest.github_login == github_login] if github_login else []
    keys += [AccessRequest.email == email] if email else []
    return bool(keys) and s.exec(select(AccessRequest.id).where(
        AccessRequest.status == "approved", or_(*keys))).first() is not None


def signup_refusal(github_login=None, email=None) -> str | None:
    """Why a new account for this GitHub login or email can't be made: "paused", "invite_only",
    or None when it can."""
    if not config.ACCEPTING:
        return "paused"
    if config.SIGNUP_MODE == "open":
        return None
    if config.SIGNUP_MODE == "allowlist":
        login, mail = (github_login or "").lower() or None, (email or "").strip().lower() or None
        if (login and login in config.ALLOWED_GITHUB) or (mail and mail in config.ALLOWED_EMAILS):
            return None
        with get_db() as s:
            if _approved(s, login, mail):
                return None
    return "invite_only"


def _find(s, github_login, email) -> AccessRequest | None:
    if github_login and (row := s.exec(select(AccessRequest).where(AccessRequest.github_login == github_login)).first()):
        return row
    if email:
        return s.exec(select(AccessRequest).where(AccessRequest.email == email)).first()
    return None


def request_access(github_login=None, email=None, note="") -> AccessRequest:
    """Store a request, or touch the one already there for this login or email: its note becomes
    the newest non-empty one, and an approved one stays approved. ValueError for a bad login."""
    github_login = normal_login(github_login) if github_login else None
    email = email.strip().lower() if email and email.strip() else None
    for attempt in (1, 2):  # a concurrent request for the same login or email may insert first
        try:
            with get_db() as s:
                row = _find(s, github_login, email)
                if row is None:
                    row = AccessRequest(github_login=github_login, email=email, note=note)
                else:
                    row.note, row.updated_at = note or row.note, utcnow()
                s.add(row)
                s.flush()
                s.refresh(row)
                return row
        except IntegrityError:
            if attempt == 2:
                raise


def find(who) -> AccessRequest | None:
    """A request by id, GitHub login (an @ is fine) or email, any case."""
    who = who.strip()
    with get_db() as s:
        if who.isdigit():
            return s.get(AccessRequest, int(who))
        who = who.lower()
        return _find(s, None, who) if "@" in who.lstrip("@") else _find(s, who.removeprefix("@"), None)


def approve(request_id) -> AccessRequest:
    with get_db() as s:
        row = s.get(AccessRequest, request_id)
        if row.status != "approved":
            row.status, row.approved_at = "approved", utcnow()
            s.add(row)
        s.flush()
        s.refresh(row)
        return row


def list_requests(status="pending") -> list[AccessRequest]:
    """Oldest first; status None: all of them."""
    with get_db() as s:
        q = select(AccessRequest).order_by(AccessRequest.created_at, AccessRequest.id)
        return list(s.exec(q.where(AccessRequest.status == status) if status else q).all())
