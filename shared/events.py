import re

from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from shared.db import get_db
from shared.models import SessionEvent, utcnow

SECRET = re.compile(
    r"x-access-token:[^@]+@"
    r"|ghs_[A-Za-z0-9]+"
    r"|\bsk-or-[A-Za-z0-9-]+"
    r"|\bsk-[A-Za-z0-9_-]{20,}"  # OpenAI: sk-..., sk-proj-..., sk-svcacct-..., sk-admin-...
)
SEQ_ATTEMPTS = 3
CHANNEL = "otto_events"  # NOTIFY channel; the payload is "<session_id>:<seq>"


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


def client_message_seq(session_id, client_message_id) -> int | None:
    """The seq of the session's message stored with this client_message_id, if any."""
    with get_db() as s:
        return s.exec(select(SessionEvent.seq).where(SessionEvent.session_id == session_id,
                                                     SessionEvent.client_message_id == client_message_id)).first()


def append_event(session_id, type, payload, client_message_id=None) -> int:
    """Store an event and return its seq (per session, starting at 1). With a client_message_id
    already stored in the session, nothing is stored: its seq comes back."""
    payload = redact(payload)
    for attempt in range(1, SEQ_ATTEMPTS + 1):
        if client_message_id and (seq := client_message_seq(session_id, client_message_id)) is not None:
            return seq
        try:
            with get_db() as s:
                last = s.exec(select(func.max(SessionEvent.seq))
                              .where(SessionEvent.session_id == session_id)).one()
                seq = (last or 0) + 1
                s.add(SessionEvent(session_id=session_id, seq=seq, ts=utcnow(),
                                   type=type, payload=payload, client_message_id=client_message_id))
                notify(s, session_id, seq)
            return seq
        except IntegrityError:
            # a concurrent writer took this seq (the composite PK caught it), or stored this
            # client_message_id first (found on the next attempt); try again. A missing session
            # also lands here, and keeps failing
            if attempt == SEQ_ATTEMPTS:
                raise


def notify(s, session_id, seq):
    """Tell listeners (the gateway) about a new event. Postgres only; SQLite has no NOTIFY.

    Sent in the event's own transaction: Postgres delivers it when that commits, and drops it
    on a rollback. The payload stays small; listeners read the row itself.
    """
    if s.get_bind().dialect.name == "postgresql":
        s.execute(text("SELECT pg_notify(:channel, :payload)"),
                  {"channel": CHANNEL, "payload": f"{session_id}:{seq}"})


def load_events(session_id, after_seq=0) -> list[SessionEvent]:
    with get_db() as s:
        return list(s.exec(select(SessionEvent)
                           .where(SessionEvent.session_id == session_id, SessionEvent.seq > after_seq)
                           .order_by(SessionEvent.seq)).all())
