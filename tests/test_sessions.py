import pytest

from shared.events import append_event, load_events
from shared.sessions import create_session, delete_session, get_session, set_status


def test_create_session_writes_row_and_created_event(db):
    create_session("s1", task="fix ghs_secret123", repo_url=None, model="m1")

    row = get_session("s1")
    assert (row.status, row.model, row.repo_url) == ("pending", "m1", None)
    assert row.task == "fix [REDACTED]"
    [ev] = load_events("s1")
    assert (ev.seq, ev.type) == (1, "session.created")
    assert ev.payload == {"task": "fix [REDACTED]", "repo_url": None, "model": "m1"}


def test_set_status_updates_row_and_emits_only_on_change(db):
    create_session("s1", task="t", repo_url="https://github.com/o/r", model="m")
    before = get_session("s1").updated_at

    set_status("s1", "running")
    set_status("s1", "running")
    set_status("s1", "done")

    row = get_session("s1")
    assert row.status == "done"
    assert row.updated_at >= before
    assert [(e.type, e.payload) for e in load_events("s1")][1:] == [
        ("session.status", {"status": "running"}),
        ("session.status", {"status": "done"}),
    ]


def test_set_status_rejects_unknown_status(db):
    create_session("s1", task="t", repo_url=None, model="m")
    with pytest.raises(ValueError):
        set_status("s1", "exploded")


def test_delete_session_removes_row_and_events(db):
    create_session("s1", task="t", repo_url=None, model="m")
    append_event("s1", "x", {})
    delete_session("s1")
    assert get_session("s1") is None
    assert load_events("s1") == []
    # the id can be reused, and seq starts over
    create_session("s1", task="t2", repo_url=None, model="m")
    assert [e.seq for e in load_events("s1")] == [1]
