from datetime import timedelta, timezone

from sqlalchemy import func
from sqlmodel import delete, select, update

from shared.db import get_db
from shared.events import append_event, redact
from shared.models import STATUSES, Session, SessionEvent, utcnow

ACTIVE = ("provisioning", "queued", "running")  # a sandbox or a worker is (about to be) busy with it
STALE_AGE = timedelta(minutes=30)     # crash sweep: only sessions older than this...
STALE_QUIET = timedelta(minutes=10)   # ...with no events for this long


def create_session(sid, task, repo_url, model, status="pending") -> Session:
    row = Session(id=sid, task=redact(task), repo_url=repo_url, model=model, status=status)
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


def transition(sid, status, allowed_from) -> bool:
    """Atomically move to `status` only from one of `allowed_from`. True if it moved."""
    if status not in STATUSES:
        raise ValueError(f"unknown session status {status!r}; expected one of {STATUSES}")
    with get_db() as s:
        r = s.exec(update(Session)
                   .where(Session.id == sid, Session.status.in_(allowed_from), Session.status != status)
                   .values(status=status, updated_at=utcnow()))
        moved = r.rowcount == 1
    if moved:
        append_event(sid, "session.status", {"status": status})
    return moved


def count_active() -> int:
    with get_db() as s:
        return s.exec(select(func.count()).select_from(Session).where(Session.status.in_(ACTIVE))).one()


def list_sessions() -> list[Session]:
    with get_db() as s:
        return list(s.exec(select(Session).order_by(Session.created_at.desc())).all())


def _utc(ts):
    # SQLite hands back naive datetimes; they were stored as UTC
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def sweep_stale_sessions() -> list[str]:
    """Mark sessions left queued/running by a dead worker as interrupted. Returns their ids."""
    now = utcnow()
    with get_db() as s:
        rows = s.exec(select(Session.id, Session.status, Session.created_at)
                      .where(Session.status.in_(("queued", "running")))).all()
        last = dict(s.exec(select(SessionEvent.session_id, func.max(SessionEvent.ts))
                           .where(SessionEvent.session_id.in_([r.id for r in rows]))
                           .group_by(SessionEvent.session_id)).all())
    swept = []
    for sid, status, created_at in rows:
        quiet_since = last.get(sid)
        if now - _utc(created_at) < STALE_AGE:
            continue
        if quiet_since is not None and now - _utc(quiet_since) < STALE_QUIET:
            continue
        if transition(sid, "interrupted", {status}):
            swept.append(sid)
    return swept
