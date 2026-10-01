from datetime import timedelta

from sqlalchemy import func
from sqlmodel import delete, select, update

from shared.db import get_db
from shared.events import append_event, redact
from shared.models import STATUSES, Session, SessionEvent, Usage, as_utc, make_title, utcnow

ACTIVE = ("provisioning", "queued", "running")  # a sandbox or a worker is (about to be) busy with it
STALE_AGE = timedelta(minutes=30)     # crash sweep: only sessions older than this...
STALE_QUIET = timedelta(minutes=10)   # ...with no events for this long


def create_session(sid, task, repo, model, status="pending", user_id=None) -> Session:
    """A new session. repo is "owner/name", or None for a plain chat; the title comes from task."""
    task = redact(task)
    row = Session(id=sid, task=task, title=make_title(task), repo=repo, model=model, status=status,
                  user_id=user_id)
    with get_db() as s:
        s.add(row)
    append_event(sid, "session.created", {"task": task, "repo": repo, "model": model})
    return row


def get_session(sid) -> Session | None:
    with get_db() as s:
        return s.get(Session, sid)


def delete_session(sid):
    """Delete the session and its events. Its usage stays (without the session): it still counts
    against the user's daily limit."""
    with get_db() as s:
        s.exec(update(Usage).where(Usage.session_id == sid).values(session_id=None))
        s.exec(delete(SessionEvent).where(SessionEvent.session_id == sid))
        s.exec(delete(Session).where(Session.id == sid))


def attach_repo(sid, repo) -> bool:
    """Give a plain chat its repo, turning it into an agent session. False if it has one already."""
    with get_db() as s:
        moved = s.exec(update(Session).where(Session.id == sid, Session.repo.is_(None))
                       .values(repo=repo, updated_at=utcnow())).rowcount == 1
    if moved:
        append_event(sid, "repo.attached", {"repo": repo})
    return moved


def set_title(sid, title):
    """Rename; doesn't count as activity, so the chat keeps its place in the list."""
    with get_db() as s:
        s.exec(update(Session).where(Session.id == sid).values(title=title))


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


def count_active_agents(user_id=None) -> int:
    """Active sessions with a repo (each has a sandbox), everyone's or one user's. Plain chats
    don't count."""
    q = select(func.count()).select_from(Session).where(Session.status.in_(ACTIVE), Session.repo.is_not(None))
    if user_id is not None:
        q = q.where(Session.user_id == user_id)
    with get_db() as s:
        return s.exec(q).one()


def list_sessions(user_id) -> list[Session]:
    """The user's sessions, most recently active first."""
    with get_db() as s:
        return list(s.exec(select(Session).where(Session.user_id == user_id)
                           .order_by(Session.updated_at.desc(), Session.created_at.desc())).all())


def repo_sessions_since(user_id, since) -> list[Session]:
    """The user's sessions with a repo that changed since `since`, newest first."""
    with get_db() as s:
        return list(s.exec(select(Session).where(Session.user_id == user_id, Session.repo.is_not(None),
                                                 Session.updated_at >= since)
                           .order_by(Session.updated_at.desc())).all())


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
        if now - as_utc(created_at) < STALE_AGE:
            continue
        if quiet_since is not None and now - as_utc(quiet_since) < STALE_QUIET:
            continue
        if transition(sid, "interrupted", {status}):
            swept.append(sid)
    return swept
