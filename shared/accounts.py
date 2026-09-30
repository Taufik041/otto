from sqlmodel import delete, or_, select

from shared.db import get_db
from shared.models import Installation, PasswordReset, Session, SessionEvent, Usage, User


def delete_account(user_id):
    """Delete a user and everything of theirs, in one transaction: their sessions with their events
    and usage, their installation links and reset tokens. Sandboxes are the caller's to stop first."""
    with get_db() as s:
        sessions = select(Session.id).where(Session.user_id == user_id)
        s.exec(delete(Usage).where(or_(Usage.user_id == user_id, Usage.session_id.in_(sessions))))
        s.exec(delete(SessionEvent).where(SessionEvent.session_id.in_(sessions)))
        s.exec(delete(Session).where(Session.user_id == user_id))
        s.exec(delete(Installation).where(Installation.user_id == user_id))
        s.exec(delete(PasswordReset).where(PasswordReset.user_id == user_id))
        s.exec(delete(User).where(User.id == user_id))
