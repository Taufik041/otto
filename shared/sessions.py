from sqlmodel import delete

from shared.db import get_db
from shared.events import append_event, redact
from shared.models import STATUSES, Session, SessionEvent, utcnow


def create_session(sid, task, repo_url, model) -> Session:
    row = Session(id=sid, task=redact(task), repo_url=repo_url, model=model, status="pending")
    with get_db() as s:
        s.add(row)
    append_event(sid, "session.created", {"task": task, "repo_url": repo_url, "model": model})
    return row


def get_session(sid) -> Session | None:
    with get_db() as s:
        return s.get(Session, sid)


def delete_session(sid):
    with get_db() as s:
        s.exec(delete(SessionEvent).where(SessionEvent.session_id == sid))
        s.exec(delete(Session).where(Session.id == sid))


def record_pr(sid, number, html_url):
    """The session's PR is open: emit pr.opened and note the PR and branch on the Session row."""
    with get_db() as s:
        row = s.get(Session, sid)
        if row is None:
            raise LookupError(f"no session {sid!r}")
        row.pr_url = html_url
        row.work_branch = f"otto/{sid}"
        row.updated_at = utcnow()
        s.add(row)
    append_event(sid, "pr.opened", {"number": number, "html_url": html_url})


def set_status(sid, status):
    """Update the session's status; emits session.status only when it actually changes."""
    if status not in STATUSES:
        raise ValueError(f"unknown session status {status!r}; expected one of {STATUSES}")
    with get_db() as s:
        row = s.get(Session, sid)
        if row is None:
            raise LookupError(f"no session {sid!r}")
        if row.status == status:
            return
        row.status = status
        row.updated_at = utcnow()
        s.add(row)
    append_event(sid, "session.status", {"status": status})
