import pytest

from shared.db import get_db
from shared.events import append_event, load_events, redact
from shared.models import Session


def make_session(sid):
    with get_db() as s:
        s.add(Session(id=sid, task="t", status="pending", model="m"))


def test_seq_is_per_session_and_ordered(db):
    make_session("a")
    make_session("b")
    assert [append_event("a", "x", {"i": i}) for i in range(3)] == [1, 2, 3]
    assert append_event("b", "y", {"i": 0}) == 1
    assert append_event("a", "x", {"i": 3}) == 4

    events = load_events("a")
    assert [e.seq for e in events] == [1, 2, 3, 4]
    assert [e.payload["i"] for e in events] == [0, 1, 2, 3]
    assert [(e.seq, e.type) for e in load_events("b")] == [(1, "y")]
    assert load_events("c") == []


def test_secrets_are_redacted_in_nested_payloads(db):
    make_session("a")
    payload = {
        "message": {"role": "tool", "content": "token=ghs_abcDEF123 ok"},
        "list": ["sk-or-v1-abc-123", {"deep": ["key sk-" + "a1" * 12 + " end"]}],
        "url": "https://x-access-token:ghs_zzz@github.com/o/r.git",
        "short": "sk-abc",  # too short to be an OpenAI key
        "n": 3, "none": None,
    }
    append_event("a", "x", payload)
    [ev] = load_events("a")
    assert ev.payload == {
        "message": {"role": "tool", "content": "token=[REDACTED] ok"},
        "list": ["[REDACTED]", {"deep": ["key [REDACTED] end"]}],
        "url": "https://[REDACTED]github.com/o/r.git",
        "short": "sk-abc",
        "n": 3, "none": None,
    }
    assert payload["message"]["content"] == "token=ghs_abcDEF123 ok"  # input not mutated


def test_redact_leaves_clean_values_alone():
    v = {"a": ["plain", 1, 2.5, True, None], "b": {"c": "tool_call ghs"}}
    assert redact(v) == v


def test_nul_characters_are_made_storable():
    # Postgres JSONB rejects \u0000; binary tool output can contain it
    assert redact({"stdout": "a\x00b"}) == {"stdout": "a�b"}


def test_append_to_unknown_session_fails(db):
    with pytest.raises(Exception):
        append_event("ghost", "x", {})
