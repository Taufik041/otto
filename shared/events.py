import re

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from shared.db import get_db
from shared.models import SessionEvent, utcnow

SECRET = re.compile(
    r"x-access-token:[^@]+@"
    r"|ghs_[A-Za-z0-9]+"
    r"|sk-or-[A-Za-z0-9-]+"
    r"|sk-[A-Za-z0-9]{20,}"
)
SEQ_ATTEMPTS = 3


def redact(value):
    """Copy of value with secrets replaced, recursively through dicts and lists."""
    if isinstance(value, str):
        # NUL is not storable in Postgres JSONB
        return SECRET.sub("[REDACTED]", value).replace("\x00", "�")
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def append_event(session_id, type, payload) -> int:
    """Store an event and return its seq (per session, starting at 1)."""
    payload = redact(payload)
    for attempt in range(1, SEQ_ATTEMPTS + 1):
        try:
            with get_db() as s:
                last = s.exec(select(func.max(SessionEvent.seq))
                              .where(SessionEvent.session_id == session_id)).one()
                seq = (last or 0) + 1
                s.add(SessionEvent(session_id=session_id, seq=seq, ts=utcnow(),
                                   type=type, payload=payload))
            return seq
        except IntegrityError:
            # a concurrent writer took this seq (the composite PK caught it); try the next one.
            # a missing session also lands here, and keeps failing
            if attempt == SEQ_ATTEMPTS:
                raise


def load_events(session_id) -> list[SessionEvent]:
    with get_db() as s:
        return list(s.exec(select(SessionEvent)
                           .where(SessionEvent.session_id == session_id)
                           .order_by(SessionEvent.seq)).all())
