"""The sidebar's dot: does a chat need the user's attention? Working, or a turn that ended done or
failed after the last event they saw. POST /sessions/{id}/seen records what they saw."""
import pytest

from shared.events import append_event
from shared.sessions import create_session, get_session, set_status
from tests.fakes import log_in_as, make_user, signup


@pytest.fixture
def client(client):
    client.user_id = signup(client)["id"]
    return client


def chat(client, sid="c1", status="running"):
    create_session(sid, task="hi", repo=None, model="m", status="pending", user_id=client.user_id)
    set_status(sid, status)
    return sid


def attention(client, sid="c1"):
    return next(s["attention"] for s in client.get("/sessions").json() if s["id"] == sid)


def last_seq(sid="c1"):
    from shared.events import load_events
    return load_events(sid)[-1].seq


@pytest.mark.parametrize("status", ["provisioning", "queued", "running"])
def test_working_while_otto_works(client, status):
    chat(client, status=status)
    assert attention(client) == "working"


@pytest.mark.parametrize("status, expected", [("done", "done"), ("failed", "failed"), ("interrupted", "failed")])
def test_a_finished_turn_wants_attention_until_seen(client, status, expected):
    chat(client)
    set_status("c1", status)
    assert attention(client) == expected

    r = client.post("/sessions/c1/seen", json={"seq": last_seq()})

    assert r.status_code == 200 and r.json() == {"last_seen_seq": last_seq()}
    assert attention(client) is None


@pytest.mark.parametrize("status", ["stopped", "pending", "limited"])
def test_no_dot_for_a_stop_the_user_made_or_anything_else(client, status):
    chat(client)
    set_status("c1", status)
    assert attention(client) is None


def test_events_after_the_end_dont_hide_it_and_a_new_end_shows_again(client):
    chat(client)
    set_status("c1", "done")
    append_event("c1", "session.titled", {"title": "t", "source": "model"})  # after the end: still unseen
    assert attention(client) == "done"
    client.post("/sessions/c1/seen", json={"seq": last_seq()})
    assert attention(client) is None

    set_status("c1", "running")  # a follow-up
    assert attention(client) == "working"
    set_status("c1", "done")
    assert attention(client) == "done"  # this end is newer than what was seen


def test_seen_never_goes_backwards(client):
    chat(client)
    set_status("c1", "done")
    end = last_seq()
    client.post("/sessions/c1/seen", json={"seq": end})

    r = client.post("/sessions/c1/seen", json={"seq": 1})  # a late, older post from another tab

    assert r.json() == {"last_seen_seq": end} and get_session("c1").last_seen_seq == end
    assert attention(client) is None


def test_seen_is_capped_at_the_chats_last_event(client):
    chat(client)
    r = client.post("/sessions/c1/seen", json={"seq": 10_000})  # can't pre-acknowledge the future
    assert r.json() == {"last_seen_seq": last_seq()}
    set_status("c1", "done")
    assert attention(client) == "done"


def test_seen_is_the_owners_only_and_validated(client):
    chat(client)
    assert client.post("/sessions/c1/seen", json={"seq": -1}).status_code == 422
    make_user("u2", email="other@example.com")
    log_in_as(client, "u2")
    assert client.post("/sessions/c1/seen", json={"seq": 1}).status_code == 404
