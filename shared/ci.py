"""CI results for the commits Otto pushes. GitHub runs the CI; Otto only reads it.

A chat's pushed head (sessions.head_sha, the last commit Otto pushed to otto/<id>) receives the
CI results for that commit, whether CI ran on the push or on the pull request. Each change is a
ci.updated event holding the whole picture for that SHA:

    {sha, state, checks: [{key, name, status, conclusion, started_at, completed_at, duration,
     html_url, job_id, updated}], url, pushed_at, run_url?, reason?}

state is one of STATES. A check is a check run ("run:<id>") or a commit status
("status:<context>"). Updates can come late or twice (webhooks, polling): a check never moves
backwards (a completed run stays completed; an older status never replaces a newer one), and a
rerun replaces the run with the same name. A new push starts over for the new SHA.

The brain records the push (pushed); the gateway records what GitHub says (record).
"""
import threading
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select, update

from shared.db import get_db
from shared.events import append_event
from shared.models import Session, SessionEvent, WebhookDelivery, as_utc, utcnow

STATES = ("queued", "running", "passed", "failed", "cancelled", "none")
# not stored: queued or running with no change for STALE_AFTER reads as "unknown" (states), so
# nothing waits on it any more; one read from GitHub (Check again) can bring it back
UNKNOWN = "unknown"
STALE_AFTER = timedelta(hours=2)
FINAL = ("passed", "failed", "cancelled", "none")  # nothing more to wait for (none: no CI seen)
EVENT = "ci.updated"
NO_CI_AFTER = timedelta(minutes=3)  # no check by then: the repo has no CI ("none")
DELIVERIES_KEPT = timedelta(days=7)

FAILED = {"failure", "timed_out", "action_required", "startup_failure"}
CANCELLED = {"cancelled", "stale"}
RANK = {"queued": 0, "waiting": 0, "requested": 0, "pending": 0, "in_progress": 1, "completed": 2}
# a commit status's state -> (status, conclusion)
STATUS_STATES = {"pending": ("in_progress", None), "success": ("completed", "success"),
                 "failure": ("completed", "failure"), "error": ("completed", "failure")}
ACTIONS_APP = "github-actions"  # its check runs are jobs: the run's id is the job's, for its logs

_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock(sid) -> threading.Lock:
    """One writer per chat at a time in this process: read the latest snapshot, merge, append."""
    with _locks_lock:
        return _locks.setdefault(sid, threading.Lock())


def iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def parse(ts) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if isinstance(ts, str) and ts else None
    except ValueError:
        return None


# --- what GitHub says, as checks ------------------------------------------------------------------

def _duration(started, completed) -> int | None:
    a, b = parse(started), parse(completed)
    return max(int((b - a).total_seconds()), 0) if a and b else None


def from_check_run(r: dict) -> dict:
    """A check run (API or webhook) as a check."""
    status = r.get("status") or "queued"
    completed = r.get("completed_at") if status == "completed" else None
    actions = ((r.get("app") or {}).get("slug")) == ACTIONS_APP
    return {"key": f"run:{r.get('id')}", "name": r.get("name") or "check", "status": status,
            "conclusion": r.get("conclusion") if status == "completed" else None,
            "started_at": r.get("started_at"), "completed_at": completed,
            "duration": _duration(r.get("started_at"), completed), "html_url": r.get("html_url") or r.get("details_url"),
            "job_id": r.get("id") if actions else None, "updated": completed or r.get("started_at")}


def from_status(st: dict) -> dict:
    """A commit status (the status webhook, or one of the combined status's) as a check."""
    status, conclusion = STATUS_STATES.get(st.get("state"), ("in_progress", None))
    updated = st.get("updated_at") or st.get("created_at")
    return {"key": f"status:{st.get('context')}", "name": st.get("context") or "status", "status": status,
            "conclusion": conclusion, "started_at": st.get("created_at"),
            "completed_at": updated if status == "completed" else None, "duration": None,
            "html_url": st.get("target_url"), "job_id": None, "updated": updated}


def _order(c) -> tuple:
    """How far along a check is: a later update never sorts below an earlier one. A status can go
    back to pending when it's set again, so only its time counts."""
    if c["key"].startswith("status:"):
        return (c.get("updated") or "",)
    return (RANK.get(c.get("status"), 0), c.get("updated") or "")


def merge(old: list[dict], new: list[dict]) -> list[dict]:
    """old's checks with new's applied: per key, the one further along; then per name, the latest
    run (a rerun replaces the run it reruns). Sorted by start, then name."""
    by_key = {c["key"]: c for c in old}
    for c in new:
        have = by_key.get(c["key"])
        if have is None or _order(c) >= _order(have):
            by_key[c["key"]] = c
    by_name: dict[str, dict] = {}
    for c in by_key.values():
        have = by_name.get(c["name"])
        if have is None or (c.get("started_at") or "", _order(c)) > (have.get("started_at") or "", _order(have)):
            by_name[c["name"]] = c
    return sorted(by_name.values(), key=lambda c: (c.get("started_at") or "", c["name"]))


def overall(checks: list[dict], pushed_at: datetime, now: datetime) -> str:
    """The state of a commit's CI. Without checks: queued for NO_CI_AFTER after the push, then none.
    It is final (passed, failed, cancelled) only once every check is complete."""
    if not checks:
        return "none" if now - pushed_at >= NO_CI_AFTER else "queued"
    waiting = [c for c in checks if c["status"] != "completed"]
    if waiting:
        started = len(waiting) < len(checks) or any(c["status"] == "in_progress" for c in waiting)
        return "running" if started else "queued"
    conclusions = {c.get("conclusion") for c in checks}
    if conclusions & FAILED:
        return "failed"
    return "cancelled" if conclusions & CANCELLED else "passed"


def failing(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c.get("conclusion") in FAILED]


def _link(state, checks, run_url) -> str | None:
    """Where "the run" is: the first failing check, else the workflow run, else the first check."""
    bad = failing(checks) if state == "failed" else []
    first = (bad or checks or [{}])[0].get("html_url")
    return bad[0].get("html_url") if bad else run_url or first


# --- the chat's snapshots --------------------------------------------------------------------------

def latest(sid) -> dict | None:
    """The chat's latest ci.updated payload."""
    with get_db() as s:
        e = s.exec(select(SessionEvent).where(SessionEvent.session_id == sid, SessionEvent.type == EVENT)
                   .order_by(SessionEvent.seq.desc()).limit(1)).first()
    return e.payload if e else None


def states(sids, now=None) -> dict[str, tuple[int, str]]:
    """Each chat's latest ci.updated: {id: (seq, state)}; chats without one are left out. CI
    queued or running with no change for STALE_AFTER is UNKNOWN."""
    if not sids:
        return {}
    with get_db() as s:
        last = (select(SessionEvent.session_id, func.max(SessionEvent.seq).label("seq"))
                .where(SessionEvent.session_id.in_(sids), SessionEvent.type == EVENT)
                .group_by(SessionEvent.session_id).subquery())
        rows = s.exec(select(SessionEvent).join(last, (SessionEvent.session_id == last.c.session_id)
                                                & (SessionEvent.seq == last.c.seq))).all()
    now = now or utcnow()
    return {e.session_id: (e.seq, _seen_state(e, now)) for e in rows}


def _seen_state(e: SessionEvent, now) -> str:
    state = e.payload.get("state")
    if state in ("queued", "running") and now - as_utc(e.ts) >= STALE_AFTER:
        return UNKNOWN
    return state


def pushed(sid, sha, now=None) -> bool:
    """Otto pushed sha to the chat's branch: CI results for it are this chat's from now on, and its
    CI starts over (queued, no checks). False if sha was the chat's already."""
    now = now or utcnow()
    with _lock(sid):
        with get_db() as s:
            s.exec(update(Session).where(Session.id == sid).values(head_sha=sha))
        prev = latest(sid)
        if prev is not None and prev.get("sha") == sha:
            return False
        append_event(sid, EVENT, {"sha": sha, "state": "queued", "checks": [], "url": None, "pushed_at": iso(now)})
        return True


def record(sid, sha, checks, run_url=None, now=None, unreadable=False) -> dict | None:
    """Fold what GitHub says about sha's CI into the chat's: the new snapshot, stored as ci.updated,
    or None if nothing changed (or sha isn't the chat's head any more). unreadable: GitHub couldn't
    be asked, so a "none" says why."""
    now = now or utcnow()
    with _lock(sid):
        with get_db() as s:
            row = s.get(Session, sid)
        if row is None or row.head_sha != sha:
            return None
        prev = latest(sid)
        if prev is None or prev.get("sha") != sha:  # a push nobody announced: start from it
            prev = None
        base = prev or {"checks": [], "pushed_at": iso(now)}
        merged = merge(base.get("checks") or [], checks)
        pushed_at = parse(base.get("pushed_at")) or now
        state = overall(merged, pushed_at, now)
        run_url = run_url or base.get("run_url")
        snap = {"sha": sha, "state": state, "checks": merged, "url": _link(state, merged, run_url),
                "pushed_at": base.get("pushed_at") or iso(now)}
        if run_url:
            snap["run_url"] = run_url
        if state == "none" and unreadable:
            snap["reason"] = "unreadable"
        if snap == prev:
            return None
        append_event(sid, EVENT, snap)
        return snap


def sessions_for(repo, sha) -> list[Session]:
    """The chats whose pushed head is sha, on repo ("owner/name", any case)."""
    with get_db() as s:
        rows = s.exec(select(Session).where(Session.head_sha == sha)).all()
    return [r for r in rows if (r.repo or "").lower() == (repo or "").lower()]


# --- webhook deliveries -----------------------------------------------------------------------------

def claim_delivery(delivery_id, event, now=None) -> bool:
    """Take a webhook delivery in: False if it was taken in already (a redelivery)."""
    try:
        with get_db() as s:
            s.add(WebhookDelivery(id=delivery_id, event=event, received_at=now or utcnow()))
        return True
    except IntegrityError:
        return False


def release_delivery(delivery_id):
    """A delivery that couldn't be queued: a redelivery may take it in."""
    with get_db() as s:
        s.exec(delete(WebhookDelivery).where(WebhookDelivery.id == delivery_id))


def prune_deliveries(now=None) -> int:
    """Forget deliveries older than DELIVERIES_KEPT. How many went."""
    with get_db() as s:
        return s.exec(delete(WebhookDelivery)
                      .where(WebhookDelivery.received_at < (now or utcnow()) - DELIVERIES_KEPT)).rowcount
