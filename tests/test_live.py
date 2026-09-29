import asyncio
from types import SimpleNamespace as NS

import pytest

from gateway import live


@pytest.fixture(autouse=True)
def no_subscribers(monkeypatch):
    monkeypatch.setattr(live, "_subscribers", {})


def drain(q):
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


@pytest.mark.asyncio
async def test_publish_fans_out_to_that_sessions_subscribers():
    a1, a2, b = live.subscribe("a"), live.subscribe("a"), live.subscribe("b")
    live.publish("a", 3)
    assert drain(a1) == [3] and drain(a2) == [3] and drain(b) == []

    live.unsubscribe("a", a1)
    live.publish("a", 4)
    assert drain(a1) == [] and drain(a2) == [4]
    live.unsubscribe("a", a2)
    live.unsubscribe("a", a2)  # twice is fine
    assert "a" not in live._subscribers


@pytest.mark.asyncio
async def test_resync_wakes_every_subscriber():
    a, b = live.subscribe("a"), live.subscribe("b")
    live.resync()
    assert drain(a) == [None] and drain(b) == [None]


@pytest.mark.asyncio
async def test_dispatch_parses_payloads_and_ignores_bad_ones():
    q = live.subscribe("abc")
    for payload in ("abc:5", "abc", "abc:x", ":1", "other:1"):
        live.dispatch(payload)
    assert drain(q) == [5]


class FakePg:
    """A LISTEN connection that delivers `payloads`, then drops (or, with hang, stays quiet)."""

    def __init__(self, payloads, hang=False):
        self.payloads, self.hang, self.executed = payloads, hang, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql):
        self.executed.append(sql)

    async def notifies(self, timeout=None):
        for p in self.payloads:
            yield NS(channel=live.CHANNEL, payload=p)
        if self.hang:
            await asyncio.Event().wait()
        raise OSError("connection lost")


@pytest.mark.asyncio
async def test_listener_reconnects_with_backoff_and_resyncs(monkeypatch):
    waits, real_sleep = [], asyncio.sleep

    async def sleep(seconds):
        waits.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    conns = [OSError("refused"), OSError("refused"), FakePg(["s:1", "s:2"]), FakePg(["s:3"], hang=True)]
    urls = []

    async def connect(url):
        urls.append(url)
        c = conns.pop(0)
        if isinstance(c, Exception):
            raise c
        return c

    q = live.subscribe("s")
    task = live.start("postgresql://x", connect=connect)
    got = [await asyncio.wait_for(q.get(), 1) for _ in range(5)]
    await live.stop(task)

    # None (a resync) after each (re)connect: anything committed while not listening is re-read
    assert got == [None, 1, 2, None, 3]
    assert waits == [1, 2, 1]
    assert urls == ["postgresql://x"] * 4
    assert task.cancelled()


def test_pg_url_drops_the_sqlalchemy_driver():
    assert (live.pg_url("postgresql+psycopg://otto:otto@localhost:5432/otto")
            == "postgresql://otto:otto@localhost:5432/otto")
