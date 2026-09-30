import pytest
from sqlmodel import select

from shared.db import get_db
from shared.events import append_event, load_events
from shared.models import Usage, make_title
from shared.sessions import attach_repo, create_session, delete_session, get_session, set_status


def test_create_session_writes_row_and_created_event(db):
    create_session("s1", task="fix ghs_secret123", repo=None, model="m1")

    row = get_session("s1")
    assert (row.status, row.model, row.repo, row.repo_url) == ("pending", "m1", None, None)
    assert row.task == "fix [REDACTED]"
    [ev] = load_events("s1")
    assert (ev.seq, ev.type) == (1, "session.created")
    assert ev.payload == {"task": "fix [REDACTED]", "repo": None, "model": "m1"}


def test_set_status_updates_row_and_emits_only_on_change(db):
    create_session("s1", task="t", repo="o/r", model="m")
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
    create_session("s1", task="t", repo=None, model="m")
    with pytest.raises(ValueError):
        set_status("s1", "exploded")


def test_delete_session_removes_row_and_events_but_keeps_the_usage(db):
    create_session("s1", task="t", repo=None, model="m")
    append_event("s1", "x", {})
    with get_db() as s:
        s.add(Usage(session_id="s1", provider="openrouter", model="m", prompt_tokens=3, completion_tokens=4))
    delete_session("s1")
    assert get_session("s1") is None
    assert load_events("s1") == []
    with get_db() as s:
        assert [(u.session_id, u.prompt_tokens) for u in s.exec(select(Usage)).all()] == [(None, 3)]
    # the id can be reused, and seq starts over
    create_session("s1", task="t2", repo=None, model="m")
    assert [e.seq for e in load_events("s1")] == [1]


def test_a_session_is_titled_by_its_first_message(db):
    create_session("s1", task="  fix the\n failing   tests " + "x" * 100, repo="o/r", model="m")
    title = get_session("s1").title
    assert title.startswith("fix the failing tests x") and len(title) == 60
    assert make_title("   ") == "New chat"
    assert make_title("a" * 59 + " b") == "a" * 59  # no trailing space


def test_attach_repo_only_to_a_plain_chat(db):
    create_session("s1", task="hi", repo=None, model="m")
    assert attach_repo("s1", "o/r") is True
    assert attach_repo("s1", "o/other") is False
    assert get_session("s1").repo == "o/r"
    assert [e.payload for e in load_events("s1") if e.type == "repo.attached"] == [{"repo": "o/r"}]
