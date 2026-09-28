import asyncio
import json
import uuid

import pytest

from shared.bus import actions_queue, results_queue, make_result
from brain.bus import bus_call, start_consumer, stop_consumer
from tests.fakes import FakeChannel


def ok(stdout):
    return {"exit_code": 0, "stdout": stdout, "stderr": ""}


async def wait_published(ch, n):
    for _ in range(1000):
        if len(ch.default_exchange.published) >= n:
            return ch.default_exchange.published
        await asyncio.sleep(0)
    raise AssertionError(f"expected {n} published actions")


@pytest.fixture
def ch():
    return FakeChannel()


@pytest.mark.asyncio
async def test_concurrent_calls_get_their_own_results_out_of_order(ch):
    results = ch.queue(results_queue("s1"))
    pending, consumer = start_consumer(results)
    try:
        calls = asyncio.gather(
            bus_call(ch, pending, "s1", "shell.exec", {"cmd": "echo a"}),
            bus_call(ch, pending, "s1", "shell.exec", {"cmd": "echo b"}),
        )
        (k1, a1), (k2, a2) = await wait_published(ch, 2)
        assert k1 == k2 == actions_queue("s1")
        # answer the second action first
        m2 = results.put(make_result(a2, True, ok("b")))
        m1 = results.put(make_result(a1, True, ok("a")))
        r1, r2 = await asyncio.wait_for(calls, 1)
    finally:
        await stop_consumer(pending, consumer)

    assert r1["stdout"] == "a"
    assert r2["stdout"] == "b"
    assert m1.acked and m2.acked
    assert pending == {}


@pytest.mark.asyncio
async def test_unknown_and_bad_results_are_dropped(ch, capsys):
    results = ch.queue(results_queue("s1"))
    pending, consumer = start_consumer(results)
    try:
        call = asyncio.ensure_future(bus_call(ch, pending, "s1", "git.status", {}))
        [(_, action)] = await wait_published(ch, 1)
        stray = results.put({"session_id": "s1", "action_id": str(uuid.uuid4()),
                             "kind": "x.result", "ok": True, "payload": ok("stray")})
        junk = results.put(b"not json")
        results.put(make_result(action, True, ok("mine")))
        r = await asyncio.wait_for(call, 1)
    finally:
        await stop_consumer(pending, consumer)

    assert r["stdout"] == "mine"
    assert stray.acked and junk.acked
    out = capsys.readouterr().out
    assert "unknown action" in out
    assert "non-JSON" in out


@pytest.mark.asyncio
async def test_timeout_returns_error_payload(ch):
    pending, consumer = start_consumer(ch.queue(results_queue("s1")))
    try:
        r = await bus_call(ch, pending, "s1", "shell.exec", {"cmd": "sleep 999"}, timeout=0.05)
    finally:
        await stop_consumer(pending, consumer)

    assert r["exit_code"] == 1
    assert r["stdout"] == ""
    assert "timed out" in r["stderr"]
    assert "shell.exec" in r["stderr"]
    assert pending == {}


@pytest.mark.asyncio
async def test_late_result_after_timeout_is_dropped(ch):
    results = ch.queue(results_queue("s1"))
    pending, consumer = start_consumer(results)
    try:
        await bus_call(ch, pending, "s1", "git.diff", {}, timeout=0.01)
        [(_, action)] = ch.default_exchange.published
        late = results.put(make_result(action, True, ok("late")))
        for _ in range(100):
            await asyncio.sleep(0)
    finally:
        await stop_consumer(pending, consumer)
    assert late.acked


def test_default_timeout_is_120s():
    import inspect
    assert inspect.signature(bus_call).parameters["timeout"].default == 120


@pytest.mark.asyncio
async def test_stop_consumer_fails_outstanding_calls(ch):
    pending, consumer = start_consumer(ch.queue(results_queue("s1")))
    call = asyncio.ensure_future(bus_call(ch, pending, "s1", "git.status", {}))
    await wait_published(ch, 1)
    await stop_consumer(pending, consumer)
    assert consumer.done()
    with pytest.raises(asyncio.CancelledError):
        await call


@pytest.mark.asyncio
async def test_record_sees_action_and_result(ch):
    results = ch.queue(results_queue("s1"))
    seen = []
    pending, consumer = start_consumer(results)
    try:
        call = asyncio.ensure_future(bus_call(ch, pending, "s1", "fs.read", {"path": "a"},
                                              record=lambda *ev: seen.append(ev)))
        [(_, action)] = await wait_published(ch, 1)
        assert seen == [("bus.action", {"action_id": action["action_id"], "kind": "fs.read",
                                        "payload": {"path": "a"}})]
        results.put(make_result(action, False, {"exit_code": 1, "stdout": "", "stderr": "no"}))
        r = await asyncio.wait_for(call, 1)
    finally:
        await stop_consumer(pending, consumer)

    assert r == {"exit_code": 1, "stdout": "", "stderr": "no"}
    assert seen[1] == ("bus.result", {"action_id": action["action_id"], "ok": False, "payload": r})


@pytest.mark.asyncio
async def test_record_sees_timeout_as_failed_result(ch):
    seen = []
    pending, consumer = start_consumer(ch.queue(results_queue("s1")))
    try:
        r = await bus_call(ch, pending, "s1", "git.diff", {}, timeout=0.01,
                           record=lambda *ev: seen.append(ev))
    finally:
        await stop_consumer(pending, consumer)
    assert [t for t, _ in seen] == ["bus.action", "bus.result"]
    assert seen[1][1]["ok"] is False and seen[1][1]["payload"] == r
