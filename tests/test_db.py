from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from shared.db import get_db
from shared.models import Session, SessionEvent


def test_session_and_event_round_trip(db):
    payload = {"message": {"role": "tool", "content": "x", "nested": [1, None, {"a": "ü"}]}}
    with get_db() as s:
        s.add(Session(id="s1", repo=None, task="do it", status="pending", model="m"))
        s.add(SessionEvent(session_id="s1", seq=1, ts=datetime.now(timezone.utc),
                           type="llm.message", payload=payload))

    with get_db() as s:
        row = s.get(Session, "s1")
        [ev] = s.exec(select(SessionEvent)).all()
    assert row.status == "pending" and row.work_branch is None
    assert row.created_at and row.updated_at
    assert ev.payload == payload


def test_event_needs_an_existing_session(db):
    with pytest.raises(IntegrityError):
        with get_db() as s:
            s.add(SessionEvent(session_id="nope", seq=1, ts=datetime.now(timezone.utc),
                               type="x", payload={}))


def test_get_db_rolls_back_on_error(db):
    with pytest.raises(RuntimeError):
        with get_db() as s:
            s.add(Session(id="s1", task="t", status="pending", model="m"))
            raise RuntimeError("boom")
    with get_db() as s:
        assert s.get(Session, "s1") is None
