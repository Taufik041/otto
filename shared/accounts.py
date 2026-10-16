"""Accounts: unconfirmed email sign-ups, and deleting an account.

Deleting one is what the Privacy Policy promises: "deleting your account deactivates it
immediately. Its data is permanently deleted, or anonymized, within 30 days." deactivate() marks
it deleted, signs out every device, drops its GitHub installations and emailed links, and frees
its email and GitHub login (another account may take them at once), keeping only hashes of them
for the purge. purge_deleted() (when the gateway starts, and daily) deletes its chats, their
events, its usage, access requests and tokens PURGE_AFTER later, and leaves an anonymous row (an
id and dates) that server logs may still name.
"""
import hashlib
from datetime import timedelta
from typing import NamedTuple

from sqlmodel import delete, func, or_, select, update

from shared.db import get_db
from shared.models import (
    AccessRequest,
    AutoReview,
    EmailVerification,
    Installation,
    PasswordReset,
    PrReview,
    RefreshToken,
    Session,
    SessionEvent,
    Usage,
    User,
    utcnow,
)
from shared.sessions import ACTIVE, set_status

UNCONFIRMED_TTL = timedelta(days=7)  # an email sign-up nobody confirmed is deleted after this
# a deleted account's data is purged this long after: the daily sweep gets to it a day later at
# most, and the nightly backups holding it are gone 14 days after that (BACKUP_KEEP_DAYS), so
# nothing of it is left within the 30 days the Privacy Policy promises
PURGE_AFTER = timedelta(days=15)
DELETED_NAME = "Deleted account"


def unconfirmed(user: User | None) -> bool:
    """An email sign-up whose owner hasn't proved the address yet: it can sign in, but not chat,
    and it reserves nothing (its address is anyone's to take)."""
    return user is not None and user.email is not None and not user.email_verified


def _delete_data(s, user_id):
    """Delete everything of the user's but the user row, in the session s."""
    sessions = select(Session.id).where(Session.user_id == user_id)
    s.exec(delete(Usage).where(or_(Usage.user_id == user_id, Usage.session_id.in_(sessions))))
    s.exec(delete(SessionEvent).where(SessionEvent.session_id.in_(sessions)))
    s.exec(delete(Session).where(Session.user_id == user_id))
    s.exec(delete(Installation).where(Installation.user_id == user_id))
    s.exec(delete(PrReview).where(PrReview.user_id == user_id))
    s.exec(delete(AutoReview).where(AutoReview.user_id == user_id))
    s.exec(delete(PasswordReset).where(PasswordReset.user_id == user_id))
    s.exec(delete(EmailVerification).where(EmailVerification.user_id == user_id))
    s.exec(delete(RefreshToken).where(RefreshToken.user_id == user_id))


def delete_rows(s, user_id):
    """Delete a user and everything of theirs in the session s (the caller's transaction): their
    sessions with their events and usage, their installation links, reset, confirmation and
    refresh tokens."""
    _delete_data(s, user_id)
    s.exec(delete(User).where(User.id == user_id))


def take_unconfirmed(s, email):
    """Delete the unconfirmed account holding email, if one does, so a new account can have it: it
    never proved the address was its own. In the caller's transaction."""
    holder = s.exec(select(User).where(User.email == email)).first()
    if unconfirmed(holder):
        delete_rows(s, holder.id)
        s.flush()


def prune_unconfirmed(now=None) -> list[str]:
    """Delete email sign-ups left unconfirmed for UNCONFIRMED_TTL; their ids. Unconfirmed, they
    can't have chats, so there are no sandboxes to stop."""
    cutoff = (now or utcnow()) - UNCONFIRMED_TTL
    with get_db() as s:
        ids = s.exec(select(User.id).where(User.email.is_not(None), User.email_verified.is_(False),
                                           User.created_at < cutoff)).all()
        for uid in ids:
            delete_rows(s, uid)
    return list(ids)


# --- deleting an account ------------------------------------------------------------------------

def deleted(user: User | None) -> bool:
    return user is not None and user.deleted_at is not None


def purge_key(kind, value) -> str:
    """What a deleted account keeps of its email ("email") or GitHub login ("github"): a hash."""
    return hashlib.sha256(f"{kind}:{value.strip().lower()}".encode()).hexdigest()


def find_account(who) -> User | None:
    """The live account with this email or GitHub login (any case, an @ is fine), or None."""
    who = who.strip().lower()
    by_email = "@" in who.lstrip("@")
    column = User.email if by_email else func.lower(User.github_login)
    with get_db() as s:
        return s.exec(select(User).where(column == (who if by_email else who.removeprefix("@")),
                                         User.deleted_at.is_(None))).first()


class Deactivated(NamedTuple):
    email: str | None  # the address it had, for the goodbye email
    github_login: str | None
    installations: list[tuple[int, str]]  # (id, account login) of the GitHub installations dropped
    sandboxes: list[str]  # its sessions with a repo: the caller stops their sandboxes


def deactivate(user_id, now=None) -> Deactivated | None:
    """Delete the account now (None if there is none, or it is deleted already): mark it deleted,
    sign out every device (token_version, refresh tokens), drop its installations and emailed
    links, stop its running sessions, and free its email and GitHub login, keeping only their
    hashes. Its chats, usage and the rest wait for purge_deleted."""
    now = now or utcnow()
    with get_db() as s:
        user = s.get(User, user_id)
        if user is None or deleted(user):
            return None
        gone = Deactivated(user.email, user.github_login,
                           [(i.id, i.account_login) for i in
                            s.exec(select(Installation).where(Installation.user_id == user_id)).all()],
                           list(s.exec(select(Session.id).where(Session.user_id == user_id,
                                                                Session.repo.is_not(None))).all()))
        active = s.exec(select(Session.id).where(Session.user_id == user_id, Session.status.in_(ACTIVE))).all()
        user.purge_keys = ([purge_key("email", user.email)] if user.email else []) + (
            [purge_key("github", user.github_login)] if user.github_login else [])
        user.deleted_at, user.token_version = now, user.token_version + 1
        user.email = user.github_id = user.github_login = user.avatar_url = None
        user.password_hash = user.default_model = None
        user.email_verified, user.name = False, DELETED_NAME
        s.add(user)
        s.exec(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=now, revoked_reason="deleted"))
        # AutoReview: its repos' new pull requests stop being reviewed on this account
        for model in (Installation, PasswordReset, EmailVerification, AutoReview):
            s.exec(delete(model).where(model.user_id == user_id))
    for sid in active:
        set_status(sid, "stopped")  # a worker on it ends after its current step
    return gone


def _purge_access_requests(s, keys):
    """Delete the access requests whose GitHub login or email hashes to one of keys."""
    if not keys:
        return
    for row in s.exec(select(AccessRequest)).all():
        if ((row.github_login and purge_key("github", row.github_login) in keys)
                or (row.email and purge_key("email", row.email) in keys)):
            s.delete(row)


def purge_deleted(now=None) -> list[str]:
    """Purge accounts deleted over PURGE_AFTER ago: delete their chats with their events, usage,
    access requests and tokens, and leave an anonymous row (id and dates). The ids it purged; a
    purged account isn't purged again."""
    now = now or utcnow()
    with get_db() as s:
        rows = s.exec(select(User).where(User.deleted_at.is_not(None), User.deleted_at <= now - PURGE_AFTER,
                                         User.purged_at.is_(None))).all()
        _purge_access_requests(s, {k for u in rows for k in u.purge_keys or []})
        for user in rows:
            _delete_data(s, user.id)
            user.purge_keys, user.purged_at = None, now
            s.add(user)
        return [u.id for u in rows]
