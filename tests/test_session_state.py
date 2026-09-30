from datetime import timedelta

from shared.db import get_db
from shared.events import append_event, load_events
from shared.models import Session, SessionEvent, utcnow
from shared.sessions import (ACTIVE, count_active_agents, create_session, get_session, list_sessions,
                             set_status, sweep_stale_sessions, transition)
from tests.fakes import make_user


def test_create_session_with_status():
    create_session("a1", task="t", repo="o/r", model="m", status="provisioning")
    assert get_session("a1").status == "provisioning"
    assert [e.type for e in load_events("a1")] == ["session.created"]


def test_transition_only_from_allowed_statuses():
    create_session("a1", task="t", repo=None, model="m", status="queued")
    assert transition("a1", "running", {"queued"}) is True
    assert transition("a1", "running", {"queued"}) is False  # already moved on
    assert transition("a1", "done", {"queued"}) is False
    assert get_session("a1").status == "running"
    assert transition("ghost", "running", {"queued"}) is False
    assert [e.payload for e in load_events("a1") if e.type == "session.status"] == [{"status": "running"}]


def test_count_and_list():
    make_user("u1")
    make_user("u2")
    for i, status in enumerate(["provisioning", "queued", "running", "done", "failed", "stopped"]):
        create_session(f"s{i}", task=f"t{i}", repo="o/r", model="m", status=status, user_id="u1")
    create_session("other", task="t", repo="o/r", model="m", status="running", user_id="u2")
    create_session("chat", task="t", repo=None, model="m", status="running", user_id="u1")  # no sandbox
    assert ACTIVE == ("provisioning", "queued", "running")
    assert (count_active_agents(), count_active_agents("u1"), count_active_agents("u2")) == (4, 3, 1)
    assert [r.id for r in list_sessions("u1")][:3] == ["chat", "s5", "s4"]  # newest first
    assert [r.id for r in list_sessions("u2")] == ["other"]


def test_load_events_after_seq():
    create_session("a1", task="t", repo=None, model="m")
    for i in range(4):
        append_event("a1", "x", {"i": i})
    assert [e.seq for e in load_events("a1", after_seq=3)] == [4, 5]


def backdate(sid, created_minutes_ago, events_minutes_ago):
    now = utcnow()
    with get_db() as s:
        row = s.get(Session, sid)
        row.created_at = now - timedelta(minutes=created_minutes_ago)
        s.add(row)
        for ev in s.exec(__import__("sqlmodel").select(SessionEvent).where(SessionEvent.session_id == sid)):
            ev.ts = now - timedelta(minutes=events_minutes_ago)
            s.add(ev)


def test_crash_sweep_marks_only_stale_active_sessions():
    cases = {  # sid: (status, created min ago, last event min ago)
        "stale-running": ("running", 60, 20),
        "stale-queued": ("queued", 45, 11),
        "young": ("running", 20, 15),       # created < 30 min ago
        "chatty": ("running", 60, 5),       # an event in the last 10 min
        "finished": ("done", 60, 20),       # not active
    }
    for sid, (status, created, last) in cases.items():
        create_session(sid, task="t", repo=None, model="m", status=status)
        backdate(sid, created, last)

    assert sorted(sweep_stale_sessions()) == ["stale-queued", "stale-running"]

    assert {sid: get_session(sid).status for sid in cases} == {
        "stale-running": "interrupted", "stale-queued": "interrupted",
        "young": "running", "chatty": "running", "finished": "done"}
    assert load_events("stale-running")[-1].type == "session.status"
