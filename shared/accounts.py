from datetime import timedelta

from sqlmodel import delete, or_, select

from shared.db import get_db
from shared.models import (EmailVerification, Installation, PasswordReset, RefreshToken, Session, SessionEvent, Usage,
                           User, utcnow)

UNCONFIRMED_TTL = timedelta(days=7)  # an email sign-up nobody confirmed is deleted after this


def unconfirmed(user: User | None) -> bool:
    """An email sign-up whose owner hasn't proved the address yet: it can sign in, but not chat,
    and it reserves nothing (its address is anyone's to take)."""
    return user is not None and user.email is not None and not user.email_verified


def delete_rows(s, user_id):
    """Delete a user and everything of theirs in the session s (the caller's transaction)."""
    sessions = select(Session.id).where(Session.user_id == user_id)
    s.exec(delete(Usage).where(or_(Usage.user_id == user_id, Usage.session_id.in_(sessions))))
    s.exec(delete(SessionEvent).where(SessionEvent.session_id.in_(sessions)))
    s.exec(delete(Session).where(Session.user_id == user_id))
    s.exec(delete(Installation).where(Installation.user_id == user_id))
    s.exec(delete(PasswordReset).where(PasswordReset.user_id == user_id))
    s.exec(delete(EmailVerification).where(EmailVerification.user_id == user_id))
    s.exec(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    s.exec(delete(User).where(User.id == user_id))


def delete_account(user_id):
    """Delete a user and everything of theirs, in one transaction: their sessions with their events
    and usage, their installation links, reset, confirmation and refresh tokens. Sandboxes are the
    caller's to stop first."""
    with get_db() as s:
        delete_rows(s, user_id)


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
